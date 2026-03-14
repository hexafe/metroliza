import logging
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


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

custom_logger_stub = types.ModuleType('modules.custom_logger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.custom_logger'] = custom_logger_stub


cmm_parser_stub = types.ModuleType('modules.cmm_report_parser')


class _DummyCmmReportParser:
    def __init__(self, *args, **kwargs):
        pass


cmm_parser_stub.CMMReportParser = _DummyCmmReportParser
sys.modules['modules.cmm_report_parser'] = cmm_parser_stub
from modules.export_data_thread import (  # noqa: E402
    ExportDataThread,
    classify_normality_status,
    build_summary_image_anchor_plan,
    build_export_dataframe,
    execute_export_query,
    run_export_steps,
)
from modules.export_backends import ExcelExportBackend  # noqa: E402
from modules.google_drive_export import GoogleDriveConversionResult  # noqa: E402
from modules.export_google_result_utils import (  # noqa: E402
    build_google_conversion_metadata,
    build_google_fallback_metadata,
    build_google_stage_message,
)
from modules.parse_reports_thread import build_report_fingerprints_from_rows, parse_new_reports  # noqa: E402


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

        from modules.parse_reports_thread import ParseReportsThread
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

        from modules.parse_reports_thread import ParseReportsThread
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



    def test_get_report_fingerprints_uses_selective_batches_and_preserves_semantics(self):
        from modules.parse_reports_thread import ParseReportsThread
        from modules.contracts import ParseRequest
        import modules.parse_reports_thread as parse_thread_module

        thread = ParseReportsThread(ParseRequest(source_directory='.', db_file='test.db'))
        thread._report_lookup_candidates = {
            'filenames': {'one.pdf', 'other.pdf'},
            'reference_dates': {('REF-A', '2024-01-01')},
        }

        original_execute = parse_thread_module.execute_with_retry
        calls = []

        def _fake_execute(_db, query, params=None, **_kwargs):
            params = params or ()
            calls.append((query, params))
            if "sqlite_master" in query:
                return [(1,)]
            if "FROM REPORTS WHERE FILENAME IN" in query:
                return [
                    (7, 'REF-A', '/tmp', 'one.pdf', '2024-01-01', '1'),
                    (None, 'REF-B', '/tmp', 'other.pdf', '2024-01-03', '2'),
                ]
            if "FROM REPORTS WHERE (REFERENCE = ? AND DATE = ?)" in query:
                return [
                    (None, 'REF-A', '/tmp', 'one.pdf', '2024-01-01', '1'),
                ]
            raise AssertionError(f"Unexpected query: {query}")

        parse_thread_module.execute_with_retry = _fake_execute
        try:
            fingerprints = thread.get_report_fingerprints_in_database()
        finally:
            parse_thread_module.execute_with_retry = original_execute

        self.assertIn('id:7', fingerprints)
        self.assertIn('REF-B|/tmp|other.pdf|2024-01-03|2', fingerprints)
        self.assertIn('REF-A|/tmp|one.pdf|2024-01-01|1', fingerprints)

        self.assertTrue(any('sqlite_master' in query for query, _ in calls))
        self.assertTrue(any('FROM REPORTS WHERE FILENAME IN' in query for query, _ in calls))
        self.assertTrue(any('FROM REPORTS WHERE (REFERENCE = ? AND DATE = ?)' in query for query, _ in calls))
        self.assertFalse(any(query.strip() == 'SELECT ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS' for query, _ in calls))


    def test_get_report_fingerprints_stops_loading_batches_on_cancel(self):
        from modules.parse_reports_thread import ParseReportsThread
        from modules.contracts import ParseRequest
        import modules.parse_reports_thread as parse_thread_module

        thread = ParseReportsThread(ParseRequest(source_directory='.', db_file='test.db'))
        thread._report_lookup_candidates = {
            'filenames': {'one.pdf', 'two.pdf', 'three.pdf'},
            'reference_dates': set(),
        }
        thread.LOOKUP_BATCH_SIZE = 1

        original_execute = parse_thread_module.execute_with_retry
        query_calls = {'batch_queries': 0}

        def _fake_execute(_db, query, params=None, **_kwargs):
            if 'sqlite_master' in query:
                return [(1,)]
            if 'FROM REPORTS WHERE FILENAME IN' in query:
                query_calls['batch_queries'] += 1
                thread.parsing_canceled = True
                return [(None, 'REF-X', '/tmp', params[0], '2024-01-01', '1')]
            return []

        parse_thread_module.execute_with_retry = _fake_execute
        try:
            fingerprints = thread.get_report_fingerprints_in_database()
        finally:
            parse_thread_module.execute_with_retry = original_execute

        self.assertEqual(query_calls['batch_queries'], 1)
        self.assertEqual(len(fingerprints), 0)

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

    def test_parse_label_includes_multiline_progress_details(self):
        from modules.parse_reports_thread import ParseReportsThread
        from modules.contracts import ParseRequest

        thread = ParseReportsThread(ParseRequest(source_directory='.', db_file='test.db'))

        label = thread._build_parse_label(parsed_files=1, total_files=4, start_time=10.0)

        self.assertIn('Parsing reports...', label)
        self.assertIn('File 1/4, remaining 3', label)
        self.assertIn('ETA --', label)

    def test_parse_progress_clamps_and_stays_monotonic(self):
        from modules.parse_reports_thread import ParseReportsThread
        from modules.contracts import ParseRequest

        captured_values = []

        class _CaptureSignal:
            def emit(self, value):
                captured_values.append(value)

        thread = ParseReportsThread(ParseRequest(source_directory='.', db_file='test.db'))
        thread.update_progress = _CaptureSignal()

        thread._emit_progress(25)
        thread._emit_progress(20)
        thread._emit_progress(120)

        self.assertEqual(captured_values, [25, 100])


class TestExportHelpers(unittest.TestCase):
    def test_build_export_dataframe_maps_columns(self):
        df = build_export_dataframe([(1, 'A')], ['ID', 'NAME'])
        self.assertEqual(list(df.columns), ['ID', 'NAME'])
        self.assertEqual(df.iloc[0]['NAME'], 'A')

    def test_classify_normality_status_maps_one_sided_not_applicable_to_neutral_badge(self):
        badge = classify_normality_status('not_applicable')

        self.assertEqual(badge['label'], 'Normality not applicable')
        self.assertEqual(badge['palette_key'], 'normality_unknown')

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

    def test_google_stage_message_builder_matches_existing_semantics(self):
        self.assertEqual(
            build_google_stage_message('completed', 'https://docs.google.com/spreadsheets/d/sheet-id/edit'),
            'Google export stage: completed (https://docs.google.com/spreadsheets/d/sheet-id/edit)',
        )
        self.assertEqual(
            build_google_stage_message('uploading'),
            'Google export stage: uploading',
        )
        self.assertEqual(
            build_google_stage_message('fallback', 'Google export timed out during upload after 61s'),
            'Google export stage: fallback (timeout: Google export timed out during upload after 61s)',
        )
        self.assertIsNone(build_google_stage_message('unknown'))

    def test_google_conversion_metadata_builder_preserves_warning_and_fallback_fields(self):
        result = GoogleDriveConversionResult(
            file_id='sheet-id',
            web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
            local_xlsx_path='out.xlsx',
            fallback_message='Use local .xlsx fallback if needed: out.xlsx',
            warnings=('chart patch skipped',),
            warning_details=('applied safe palette',),
            converted_tab_titles=('MEASUREMENTS',),
        )

        metadata = build_google_conversion_metadata(result)

        self.assertEqual(metadata['converted_url'], 'https://docs.google.com/spreadsheets/d/sheet-id/edit')
        self.assertEqual(metadata['local_xlsx_path'], 'out.xlsx')
        self.assertEqual(metadata['fallback_message'], 'Use local .xlsx fallback if needed: out.xlsx')
        self.assertEqual(metadata['conversion_warnings'], ['chart patch skipped'])
        self.assertEqual(metadata['conversion_warning_details'], ['applied safe palette'])
        self.assertEqual(metadata['converted_tab_titles'], ['MEASUREMENTS'])

    def test_google_fallback_metadata_builder_preserves_local_fallback_contract(self):
        metadata = build_google_fallback_metadata(
            excel_file='out.xlsx',
            error=RuntimeError('temporary outage'),
        )

        self.assertIn('Google export failed; using local .xlsx fallback: out.xlsx', metadata['fallback_message'])
        self.assertEqual(metadata['fallback_reason'], 'network')
        self.assertEqual(metadata['conversion_warnings'], ['temporary outage'])

    def test_check_canceled_emits_cancel_signal_once(self):
        request = __import__('modules.contracts', fromlist=['ExportRequest', 'AppPaths', 'ExportOptions'])
        thread = ExportDataThread(
            request.ExportRequest(
                paths=request.AppPaths(db_file=':memory:', excel_file='dummy.xlsx'),
                options=request.ExportOptions(),
            )
        )

        calls = {'count': 0}

        class _Signal:
            def emit(self, *_args, **_kwargs):
                calls['count'] += 1

        thread.canceled = _Signal()
        thread.update_label = _Signal()
        thread.export_canceled = True

        self.assertTrue(thread._check_canceled())
        self.assertTrue(thread._check_canceled())
        self.assertEqual(calls['count'], 2)


class TestExportBackendSmoke(unittest.TestCase):
    @staticmethod
    def _build_fake_measurement_backend():
        class _FakeWorksheet:
            def set_column(self, *_args, **_kwargs):
                return None

            def freeze_panes(self, *_args, **_kwargs):
                return None

        class _FakeWorkbook:
            def add_worksheet(self, _name):
                return _FakeWorksheet()

        class _FakeBackend:
            def __init__(self):
                self._workbook = _FakeWorkbook()

            def get_workbook(self, _excel_writer):
                return self._workbook

            def list_sheet_names(self, _excel_writer):
                return set()

        return _FakeBackend()

    @staticmethod
    def _build_multi_header_measurement_dataframe():
        import pandas as pd

        rows = []
        references = ('REF_A', 'REF_B')
        headers = ('H1', 'H2', 'H3')
        for ref in references:
            for header in headers:
                for sample_idx in range(1, 3):
                    rows.append(
                        {
                            'REFERENCE': ref,
                            'HEADER - AX': header,
                            'NOM': 10.0,
                            '+TOL': 1.0,
                            '-TOL': -1.0,
                            'BONUS': 0.0,
                            'MEAS': 10.0 + sample_idx,
                            'DATE': f'2024-01-0{sample_idx}',
                            'SAMPLE_NUMBER': str(sample_idx),
                        }
                    )

        return pd.DataFrame(rows)

    def test_export_run_emits_monotonic_progress_from_zero_to_hundred_for_multi_header_data(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
        previous_reader = module.read_sql_dataframe
        previous_builder = module.build_measurement_export_dataframe
        previous_formats = module.create_measurement_formats
        previous_write_block = module.write_measurement_block
        previous_insert_chart = module.insert_measurement_chart
        previous_fetch_partition_values = module.fetch_partition_values
        previous_fetch_partition_header_counts = module.fetch_partition_header_counts
        previous_load_measurement_partition = module.load_measurement_export_partition_dataframe

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)
            thread._export_df_cache = object()
            thread._export_df_column_order = ()
            fake_backend = self._build_fake_measurement_backend()

            class _BackendRunner:
                def run(self, runner_thread):
                    return runner_thread.run_export_pipeline(excel_writer=object())

            progress_values = []
            thread.get_export_backend = lambda: _BackendRunner()
            thread.add_measurements_horizontal_sheet = lambda *_args, **_kwargs: None
            thread.export_filtered_data = lambda *_: None
            thread.update_progress.emit = lambda value: progress_values.append(value)
            thread.update_label.emit = lambda *_: None
            thread.finished.emit = lambda: None
            thread._active_backend = fake_backend
            thread._write_group_comparison_sheet = lambda *_args, **_kwargs: None

            measurement_df = self._build_multi_header_measurement_dataframe()
            module.fetch_partition_values = lambda *_args, **_kwargs: ['REF_A', 'REF_B']
            module.fetch_partition_header_counts = lambda *_args, **_kwargs: {'REF_A': 3, 'REF_B': 3}
            module.load_measurement_export_partition_dataframe = (
                lambda *_args, partition_value=None, **_kwargs: measurement_df[measurement_df['REFERENCE'] == partition_value].copy()
            )
            module.read_sql_dataframe = lambda *_args, **_kwargs: __import__('pandas').DataFrame()
            module.build_measurement_export_dataframe = lambda *_args, **_kwargs: measurement_df
            module.create_measurement_formats = lambda *_args, **_kwargs: {'default': object(), 'border': object()}
            module.write_measurement_block = lambda *_args, **_kwargs: {'first_data_row': 0, 'last_data_row': 0}
            module.insert_measurement_chart = lambda *_args, **_kwargs: None
            try:
                thread.run()
            finally:
                module.read_sql_dataframe = previous_reader
                module.build_measurement_export_dataframe = previous_builder
                module.create_measurement_formats = previous_formats
                module.write_measurement_block = previous_write_block
                module.insert_measurement_chart = previous_insert_chart
                module.fetch_partition_values = previous_fetch_partition_values
                module.fetch_partition_header_counts = previous_fetch_partition_header_counts
                module.load_measurement_export_partition_dataframe = previous_load_measurement_partition

        self.assertEqual(progress_values[0], 0)
        self.assertEqual(progress_values[-1], 100)
        self.assertEqual(progress_values, sorted(progress_values))
        self.assertGreater(len(progress_values), 3)

    def test_add_measurements_stops_emitting_progress_when_canceled(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
        previous_reader = module.read_sql_dataframe
        previous_builder = module.build_measurement_export_dataframe
        previous_formats = module.create_measurement_formats
        previous_write_block = module.write_measurement_block
        previous_insert_chart = module.insert_measurement_chart
        previous_fetch_partition_values = module.fetch_partition_values
        previous_fetch_partition_header_counts = module.fetch_partition_header_counts
        previous_load_measurement_partition = module.load_measurement_export_partition_dataframe

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)
            thread._export_df_cache = object()
            thread._export_df_column_order = ()
            thread._active_backend = self._build_fake_measurement_backend()
            thread._write_group_comparison_sheet = lambda *_args, **_kwargs: None

            progress_values = []
            cancellation_state = {'triggered': False}
            cancel_probe = {'checks': 0}

            def _check_canceled():
                cancel_probe['checks'] += 1
                if cancel_probe['checks'] >= 1:
                    cancellation_state['triggered'] = True
                    return True
                return False

            thread._check_canceled = _check_canceled
            thread.update_progress.emit = lambda value: progress_values.append(value)
            thread.update_label.emit = lambda *_: None

            measurement_df = self._build_multi_header_measurement_dataframe()
            module.fetch_partition_values = lambda *_args, **_kwargs: ['REF_A', 'REF_B']
            module.fetch_partition_header_counts = lambda *_args, **_kwargs: {'REF_A': 3, 'REF_B': 3}
            module.load_measurement_export_partition_dataframe = (
                lambda *_args, partition_value=None, **_kwargs: measurement_df[measurement_df['REFERENCE'] == partition_value].copy()
            )
            module.read_sql_dataframe = lambda *_args, **_kwargs: object()
            module.build_measurement_export_dataframe = lambda *_args, **_kwargs: measurement_df
            module.create_measurement_formats = lambda *_args, **_kwargs: {'default': object(), 'border': object()}
            module.write_measurement_block = lambda *_args, **_kwargs: {'first_data_row': 0, 'last_data_row': 0}
            module.insert_measurement_chart = lambda *_args, **_kwargs: None
            try:
                thread.add_measurements_horizontal_sheet(excel_writer=object())
            finally:
                module.read_sql_dataframe = previous_reader
                module.build_measurement_export_dataframe = previous_builder
                module.create_measurement_formats = previous_formats
                module.write_measurement_block = previous_write_block
                module.insert_measurement_chart = previous_insert_chart
                module.fetch_partition_values = previous_fetch_partition_values
                module.fetch_partition_header_counts = previous_fetch_partition_header_counts
                module.load_measurement_export_partition_dataframe = previous_load_measurement_partition

        self.assertTrue(cancellation_state['triggered'])
        self.assertLessEqual(len(progress_values), 1)
        if progress_values:
            self.assertLess(progress_values[-1], 95)

    def test_add_measurements_emits_reference_and_header_label_details(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
        previous_reader = module.read_sql_dataframe
        previous_builder = module.build_measurement_export_dataframe
        previous_formats = module.create_measurement_formats
        previous_write_block = module.write_measurement_block
        previous_insert_chart = module.insert_measurement_chart
        previous_fetch_partition_values = module.fetch_partition_values
        previous_fetch_partition_header_counts = module.fetch_partition_header_counts
        previous_load_measurement_partition = module.load_measurement_export_partition_dataframe
        previous_perf_counter = module.time.perf_counter

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)
            thread._export_df_cache = object()
            thread._export_df_column_order = ()
            thread._active_backend = self._build_fake_measurement_backend()
            thread._write_group_comparison_sheet = lambda *_args, **_kwargs: None

            labels = []
            counter = {'value': 0.0}

            def _fake_perf_counter():
                counter['value'] += 0.6
                return counter['value']

            thread.update_label.emit = lambda text: labels.append(text)
            thread.update_progress.emit = lambda *_: None

            measurement_df = self._build_multi_header_measurement_dataframe()
            module.fetch_partition_values = lambda *_args, **_kwargs: ['REF_A', 'REF_B']
            module.fetch_partition_header_counts = lambda *_args, **_kwargs: {'REF_A': 3, 'REF_B': 3}
            module.load_measurement_export_partition_dataframe = (
                lambda *_args, partition_value=None, **_kwargs: measurement_df[measurement_df['REFERENCE'] == partition_value].copy()
            )
            module.read_sql_dataframe = lambda *_args, **_kwargs: object()
            module.build_measurement_export_dataframe = lambda *_args, **_kwargs: measurement_df
            module.create_measurement_formats = lambda *_args, **_kwargs: {'default': object(), 'border': object()}
            module.write_measurement_block = lambda *_args, **_kwargs: {'first_data_row': 0, 'last_data_row': 0}
            module.insert_measurement_chart = lambda *_args, **_kwargs: None
            module.time.perf_counter = _fake_perf_counter
            try:
                thread.add_measurements_horizontal_sheet(excel_writer=object())
            finally:
                module.read_sql_dataframe = previous_reader
                module.build_measurement_export_dataframe = previous_builder
                module.create_measurement_formats = previous_formats
                module.write_measurement_block = previous_write_block
                module.insert_measurement_chart = previous_insert_chart
                module.fetch_partition_values = previous_fetch_partition_values
                module.fetch_partition_header_counts = previous_fetch_partition_header_counts
                module.load_measurement_export_partition_dataframe = previous_load_measurement_partition
                module.time.perf_counter = previous_perf_counter

        detailed_labels = [text for text in labels if text.startswith('Building measurement sheets...')]
        self.assertTrue(detailed_labels)
        self.assertTrue(any('Ref 1/2' in text for text in detailed_labels))
        self.assertTrue(any('Ref 2/2' in text for text in detailed_labels))
        self.assertTrue(all('Headers remaining ' in text for text in detailed_labels))
        self.assertTrue(all(text.count('\n') >= 2 for text in detailed_labels))

    def test_add_measurements_creates_summary_tab_immediately_after_each_reference_tab(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
        previous_reader = module.read_sql_dataframe
        previous_builder = module.build_measurement_export_dataframe
        previous_formats = module.create_measurement_formats
        previous_write_block = module.write_measurement_block
        previous_insert_chart = module.insert_measurement_chart
        previous_fetch_partition_values = module.fetch_partition_values
        previous_fetch_partition_header_counts = module.fetch_partition_header_counts
        previous_load_measurement_partition = module.load_measurement_export_partition_dataframe

        class _FakeWorksheet:
            def set_column(self, *_args, **_kwargs):
                return None

            def freeze_panes(self, *_args, **_kwargs):
                return None

        class _RecordingWorkbook:
            def __init__(self):
                self.added_sheet_names = []

            def add_worksheet(self, name):
                self.added_sheet_names.append(name)
                return _FakeWorksheet()

        class _Backend:
            def __init__(self, workbook):
                self._workbook = workbook

            def get_workbook(self, _excel_writer):
                return self._workbook

            def list_sheet_names(self, _excel_writer):
                return set(self._workbook.added_sheet_names)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(generate_summary_sheet=True),
            )
            thread = ExportDataThread(request)
            thread._export_df_cache = object()
            thread._export_df_column_order = ()
            workbook = _RecordingWorkbook()
            thread._active_backend = _Backend(workbook)
            thread._write_group_comparison_sheet = lambda *_args, **_kwargs: None
            thread.update_progress.emit = lambda *_: None
            thread.update_label.emit = lambda *_: None

            measurement_df = self._build_multi_header_measurement_dataframe()
            module.fetch_partition_values = lambda *_args, **_kwargs: ['REF_A', 'REF_B']
            module.fetch_partition_header_counts = lambda *_args, **_kwargs: {'REF_A': 3, 'REF_B': 3}
            module.load_measurement_export_partition_dataframe = (
                lambda *_args, partition_value=None, **_kwargs: measurement_df[measurement_df['REFERENCE'] == partition_value].copy()
            )
            module.read_sql_dataframe = lambda *_args, **_kwargs: object()
            module.build_measurement_export_dataframe = lambda *_args, **_kwargs: measurement_df
            module.create_measurement_formats = lambda *_args, **_kwargs: {'default': object(), 'border': object()}
            module.write_measurement_block = lambda *_args, **_kwargs: {'first_data_row': 0, 'last_data_row': 0}
            module.insert_measurement_chart = lambda *_args, **_kwargs: None
            thread.summary_sheet_fill = lambda *_args, **_kwargs: None
            try:
                thread.add_measurements_horizontal_sheet(excel_writer=object())
            finally:
                module.read_sql_dataframe = previous_reader
                module.build_measurement_export_dataframe = previous_builder
                module.create_measurement_formats = previous_formats
                module.write_measurement_block = previous_write_block
                module.insert_measurement_chart = previous_insert_chart
                module.fetch_partition_values = previous_fetch_partition_values
                module.fetch_partition_header_counts = previous_fetch_partition_header_counts
                module.load_measurement_export_partition_dataframe = previous_load_measurement_partition

        self.assertEqual(
            workbook.added_sheet_names,
            ['REF_A', 'REF_A_summary', 'REF_B', 'REF_B_summary'],
        )

    def test_add_measurements_applies_default_column_formatting_through_last_generated_block_column(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
        previous_formats = module.create_measurement_formats
        previous_write_block = module.write_measurement_block
        previous_insert_chart = module.insert_measurement_chart
        previous_fetch_partition_header_counts = module.fetch_partition_header_counts

        class _RecordingWorksheet:
            def __init__(self):
                self.set_column_calls = []

            def set_column(self, first_col, last_col, width=None, cell_format=None, options=None):
                self.set_column_calls.append((first_col, last_col, width, cell_format, options))

            def freeze_panes(self, *_args, **_kwargs):
                return None

        class _RecordingWorkbook:
            def __init__(self):
                self.added_sheet_names = []
                self.worksheets = {}

            def add_worksheet(self, name):
                worksheet = _RecordingWorksheet()
                self.added_sheet_names.append(name)
                self.worksheets[name] = worksheet
                return worksheet

        class _Backend:
            def __init__(self, workbook):
                self._workbook = workbook

            def get_workbook(self, _excel_writer):
                return self._workbook

            def list_sheet_names(self, _excel_writer):
                return set(self._workbook.added_sheet_names)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)
            thread._export_df_cache = object()
            thread._export_df_column_order = ()
            workbook = _RecordingWorkbook()
            thread._active_backend = _Backend(workbook)
            thread._write_group_comparison_sheet = lambda *_args, **_kwargs: None
            thread.update_progress.emit = lambda *_: None
            thread.update_label.emit = lambda *_: None

            header_count = 16
            headers = [f'H{idx:02d}' for idx in range(1, header_count + 1)]
            measurement_df = pd.DataFrame(
                {
                    'REFERENCE': ['REF_A'] * header_count,
                    'HEADER - AX': headers,
                    'NOM': [10.0] * header_count,
                    '+TOL': [1.0] * header_count,
                    '-TOL': [-1.0] * header_count,
                    'BONUS': [0.0] * header_count,
                    'MEAS': [10.0] * header_count,
                    'DATE': ['2024-01-01'] * header_count,
                    'SAMPLE_NUMBER': ['1'] * header_count,
                }
            )

            module.fetch_partition_header_counts = lambda *_args, **_kwargs: {'REF_A': header_count}
            thread._iter_reference_partitions = lambda: iter([('REF_A', measurement_df.copy())])
            module.create_measurement_formats = lambda *_args, **_kwargs: {'default': object(), 'border': object()}
            module.write_measurement_block = lambda *_args, **_kwargs: {'first_data_row': 0, 'last_data_row': 0}
            module.insert_measurement_chart = lambda *_args, **_kwargs: None
            try:
                thread.add_measurements_horizontal_sheet(excel_writer=object())
            finally:
                module.create_measurement_formats = previous_formats
                module.write_measurement_block = previous_write_block
                module.insert_measurement_chart = previous_insert_chart
                module.fetch_partition_header_counts = previous_fetch_partition_header_counts

        worksheet = workbook.worksheets['REF_A']
        first_set_column = worksheet.set_column_calls[0]
        self.assertEqual(first_set_column[0], 0)
        self.assertEqual(first_set_column[1], (header_count * 5) - 1)

    def test_summary_sheet_fill_populates_iqr_slot_for_each_header_when_deferred_charts_enabled(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['defer_non_essential_charts'] = True

        worksheet = _FakeSummaryWorksheet()
        headers = {
            'H1': pd.DataFrame(
                {
                    'MEAS': [9.9, 10.0, 10.2, 10.1, 10.05, 9.95],
                    'NOM': [10.0] * 6,
                    '+TOL': [0.2] * 6,
                    '-TOL': [-0.2] * 6,
                    'SAMPLE_NUMBER': ['1', '2', '3', '4', '5', '6'],
                    'DATE': ['2024-01-01'] * 6,
                }
            ),
            'H2': pd.DataFrame(
                {
                    'MEAS': [5.1, 5.2, 5.0, 5.15, 5.25, 5.18],
                    'NOM': [5.1] * 6,
                    '+TOL': [0.3] * 6,
                    '-TOL': [-0.3] * 6,
                    'SAMPLE_NUMBER': ['1', '2', '3', '4', '5', '6'],
                    'DATE': ['2024-01-02'] * 6,
                }
            ),
        }

        for index, (header, header_group) in enumerate(headers.items(), start=1):
            thread.summary_sheet_fill(worksheet, header, header_group, col=index * 5)

        inserted_positions = set(worksheet.inserted_images)
        expected_iqr_positions = {
            build_summary_image_anchor_plan(index * 5)['iqr']
            for index in range(1, len(headers) + 1)
        }

        self.assertTrue(expected_iqr_positions.issubset(inserted_positions))
        self.assertEqual(len(expected_iqr_positions), 2)


    def test_summary_sheet_fill_includes_histogram_and_trend_slots_without_palette_key_errors(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)

        worksheet = _FakeSummaryWorksheet()
        header_group = pd.DataFrame(
            {
                'MEAS': [9.9, 10.0, 10.2, 10.1, 10.05, 9.95],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '2', '3', '4', '5', '6'],
                'DATE': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-06'],
            }
        )

        thread.summary_sheet_fill(worksheet, 'H1', header_group, col=5)

        inserted_positions = set(worksheet.inserted_images)
        panel_slots = build_summary_image_anchor_plan(5)

        self.assertIn(panel_slots['histogram'], inserted_positions)
        self.assertIn(panel_slots['trend'], inserted_positions)

    def test_apply_bottleneck_optimizations_preserves_trend_for_normal_runs(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._stage_timings.update(
            {
                'chart_rendering': 70.0,
                'transform_grouping': 20.0,
                'worksheet_writes': 10.0,
            }
        )

        thread._apply_bottleneck_optimizations()

        self.assertTrue(thread._optimization_toggles['defer_non_essential_charts'])
        self.assertEqual(
            thread._optimization_toggles['summary_sheet_minimum_charts'],
            {'distribution', 'iqr', 'histogram', 'trend'},
        )
        self.assertTrue(thread._summary_chart_required('iqr'))
        self.assertTrue(thread._summary_chart_required('trend'))

    def test_apply_bottleneck_optimizations_can_skip_trend_when_opted_in(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(
                generate_summary_sheet=True,
                allow_non_essential_chart_skipping=True,
            ),
        )
        thread = ExportDataThread(request)
        thread._stage_timings.update(
            {
                'chart_rendering': 70.0,
                'transform_grouping': 20.0,
                'worksheet_writes': 10.0,
            }
        )

        thread._apply_bottleneck_optimizations()

        self.assertTrue(thread._optimization_toggles['defer_non_essential_charts'])
        self.assertEqual(thread._optimization_toggles['summary_sheet_minimum_charts'], {'distribution', 'iqr', 'histogram'})
        self.assertFalse(thread._summary_chart_required('trend'))

    def test_summary_sheet_fill_deferred_mode_still_renders_trend_by_default(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['defer_non_essential_charts'] = True
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution', 'iqr', 'histogram', 'trend'}

        worksheet = _FakeSummaryWorksheet()
        header_group = pd.DataFrame(
            {
                'MEAS': [9.9, 10.0, 10.2, 10.1, 10.05, 9.95],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '2', '3', '4', '5', '6'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        thread.summary_sheet_fill(worksheet, 'H1', header_group, col=5)

        inserted_positions = set(worksheet.inserted_images)
        panel_slots = build_summary_image_anchor_plan(5)
        self.assertEqual(
            inserted_positions,
            {
                panel_slots['distribution'],
                panel_slots['iqr'],
                panel_slots['histogram'],
                panel_slots['trend'],
            },
        )


    def test_run_initializes_and_shuts_down_shared_chart_executor_once_when_enabled(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['enable_chart_multiprocessing'] = True

        class _Backend:
            def run(self, _thread):
                return True

        thread.get_export_backend = lambda: _Backend()
        thread.update_label.emit = lambda *_: None
        thread.update_progress.emit = lambda *_: None
        thread.finished.emit = lambda: None

        module = __import__('modules.export_data_thread', fromlist=['ProcessPoolExecutor'])
        previous_executor = module.ProcessPoolExecutor

        calls = {'init': 0, 'shutdown': 0}

        class _FakeExecutor:
            def __init__(self, *args, **kwargs):
                calls['init'] += 1

            def shutdown(self, wait=True):
                calls['shutdown'] += 1

        module.ProcessPoolExecutor = _FakeExecutor
        try:
            thread.run()
        finally:
            module.ProcessPoolExecutor = previous_executor

        self.assertEqual(calls['init'], 1)
        self.assertEqual(calls['shutdown'], 1)
        self.assertIsNone(thread._chart_executor)

    def test_summary_sheet_fill_uses_executor_precompute_for_large_original_groups(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        class _ImmediateFuture:
            def __init__(self, value):
                self._value = value

            def result(self):
                return self._value

        class _RecordingExecutor:
            def __init__(self):
                self.calls = []

            def submit(self, fn, *args, **kwargs):
                self.calls.append((fn.__name__, args, kwargs))
                return _ImmediateFuture(fn(*args, **kwargs))

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        executor = _RecordingExecutor()
        thread._chart_executor = executor

        worksheet = _FakeSummaryWorksheet()
        row_count = 2600
        header_group = pd.DataFrame(
            {
                'MEAS': [10.0 + (idx % 9) * 0.01 for idx in range(row_count)],
                'NOM': [10.0] * row_count,
                '+TOL': [0.2] * row_count,
                '-TOL': [-0.2] * row_count,
                'SAMPLE_NUMBER': [str(idx + 1) for idx in range(row_count)],
                'DATE': ['2024-01-01'] * row_count,
            }
        )

        thread.summary_sheet_fill(worksheet, 'H1', header_group, col=5)

        self.assertEqual(len(executor.calls), 2)
        sampled_limit = thread._chart_sample_limit()
        self.assertLessEqual(len(executor.calls[0][1][0]), sampled_limit)
        self.assertEqual(len(executor.calls[0][1][0]), len(executor.calls[1][1][0]))

    def test_summary_sheet_fill_falls_back_to_in_process_when_executor_submit_fails(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        class _BrokenExecutor:
            def submit(self, *_args, **_kwargs):
                raise RuntimeError('executor unavailable')

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._chart_executor = _BrokenExecutor()

        worksheet = _FakeSummaryWorksheet()
        row_count = 2600
        header_group = pd.DataFrame(
            {
                'MEAS': [10.0 + (idx % 9) * 0.01 for idx in range(row_count)],
                'NOM': [10.0] * row_count,
                '+TOL': [0.2] * row_count,
                '-TOL': [-0.2] * row_count,
                'SAMPLE_NUMBER': [str(idx + 1) for idx in range(row_count)],
                'DATE': ['2024-01-01'] * row_count,
            }
        )

        thread.summary_sheet_fill(worksheet, 'H1', header_group, col=5)

        panel_slots = build_summary_image_anchor_plan(5)
        inserted_positions = set(worksheet.inserted_images)
        self.assertIn(panel_slots['histogram'], inserted_positions)
        self.assertIn(panel_slots['trend'], inserted_positions)

    def test_build_iqr_plot_payload_rebuilds_safe_fallback_on_length_mismatch(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)

        sampled_group = pd.DataFrame({'MEAS': [1.0, 2.0, 3.0]})
        labels = ['A', 'B']
        values = [[1.0, 2.0]]

        iqr_labels, iqr_values = thread._build_iqr_plot_payload(labels, values, sampled_group)

        self.assertEqual(iqr_labels, ['All'])
        self.assertEqual(iqr_values, [[1.0, 2.0, 3.0]])

    def test_grouped_summary_scatter_payload_appends_group_sample_sizes_to_labels(self):
        import pandas as pd

        header_group = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B', 'B', 'B'],
                'MEAS': [1.0, 2.0, 5.0, 5.5, 6.0],
            }
        )

        _x, _y, labels = ExportDataThread._build_grouped_summary_scatter_payload(
            header_group,
            'GROUP',
            grouping_active=True,
        )

        self.assertEqual(labels, ['A (n=2)', 'B (n=3)'])

    def test_build_iqr_plot_payload_keeps_group_labels_dense_when_grouping_active(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)

        sampled_group = pd.DataFrame({'MEAS': [1.0, 2.0, 3.0, 4.0]})
        labels = ['G1', 'G1', 'G2', 'G2']
        values = [[1.0, 2.0], [3.0, 4.0], [2.0, 2.5], [3.5, 3.8]]

        iqr_labels, iqr_values = thread._build_iqr_plot_payload(
            labels,
            values,
            sampled_group,
            grouping_active=True,
        )

        self.assertEqual(iqr_labels, ['G1', 'G1', 'G2', 'G2'])
        self.assertEqual(iqr_values, values)

    def test_render_iqr_boxplot_normalizes_mismatched_inputs_without_raising(self):
        import matplotlib.pyplot as plt

        module = __import__('modules.export_data_thread', fromlist=['render_iqr_boxplot'])
        fig, ax = plt.subplots(figsize=(4, 3))
        try:
            module.render_iqr_boxplot(ax, values=[[1, 2, 3], [4, 5, 6]], labels=['One'])
        finally:
            plt.close(fig)

    def test_summary_sheet_fill_can_render_violin_false_completes_without_raising(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def __init__(self):
                self.inserted_images = []

            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, row, col, *_args, **_kwargs):
                self.inserted_images.append((row, col))

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread.violin_plot_min_samplesize = 10

        worksheet = _FakeSummaryWorksheet()
        header_group = pd.DataFrame(
            {
                'MEAS': [9.9, 10.0, 10.2, 10.1, 10.05, 9.95],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '1', '2', '2', '3', '3'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        thread.summary_sheet_fill(worksheet, 'H1', header_group, col=5)

        panel_slots = build_summary_image_anchor_plan(5)
        inserted_positions = set(worksheet.inserted_images)
        self.assertIn(panel_slots['distribution'], inserted_positions)
        self.assertIn(panel_slots['iqr'], inserted_positions)

    def test_summary_sheet_distribution_scatter_fallback_uses_group_bucket_labels(self):
        import pandas as pd

        import modules.export_data_thread as export_thread_module
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution'}
        thread.violin_plot_min_samplesize = 3

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05],
                'NOM': [10.0] * 5,
                '+TOL': [0.2] * 5,
                '-TOL': [-0.2] * 5,
                'SAMPLE_NUMBER': ['1', '2', '3', '4', '5'],
                'DATE': ['2024-01-01'] * 5,
            }
        )
        grouped_header = header_group.assign(GROUP=['A', 'A', 'B', 'B', 'C'])
        thread._prepared_grouping_df = pd.DataFrame()
        thread._apply_group_assignments = lambda hg, _gd: (grouped_header.copy(), True)

        captured = {}
        original_apply_labels = export_thread_module.apply_shared_x_axis_label_strategy
        try:
            def _capture_labels(_ax, labels, **kwargs):
                captured['labels'] = list(labels)
                captured['positions'] = list(kwargs.get('positions') or [])
                return None

            export_thread_module.apply_shared_x_axis_label_strategy = _capture_labels

            thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)
        finally:
            export_thread_module.apply_shared_x_axis_label_strategy = original_apply_labels

        self.assertEqual(captured['labels'], ['A (n=2)', 'B (n=2)', 'C (n=1)'])
        self.assertEqual(captured['positions'], [0.0, 1.0, 2.0])

    def test_summary_sheet_distribution_scatter_fallback_non_grouped_sample_number_labels(self):
        import pandas as pd

        import modules.export_data_thread as export_thread_module
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution'}
        thread.violin_plot_min_samplesize = 3

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05, 10.02],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '1', '2', '2', '3', '3'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        captured = {}
        original_apply_labels = export_thread_module.apply_shared_x_axis_label_strategy
        try:
            def _capture_labels(_ax, labels, **kwargs):
                captured['labels'] = list(labels)
                captured['positions'] = list(kwargs.get('positions') or [])
                return None

            export_thread_module.apply_shared_x_axis_label_strategy = _capture_labels

            thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)
        finally:
            export_thread_module.apply_shared_x_axis_label_strategy = original_apply_labels

        self.assertEqual(captured['labels'], ['1', '2', '3'])
        self.assertEqual(captured['positions'], [0.0, 1.0, 2.0])

    def test_summary_sheet_trend_axis_title_uses_group_label_when_grouped(self):
        import pandas as pd

        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'trend'}

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05, 10.02],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '1', '2', '2', '3', '3'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        grouped_header = header_group.assign(GROUP=['A', 'A', 'B', 'B', 'C', 'C'])
        thread._prepared_grouping_df = pd.DataFrame()

        for grouping_active, expected_label in ((False, 'Sample #'), (True, 'Group')):
            with self.subTest(grouping_active=grouping_active):
                if grouping_active:
                    thread._apply_group_assignments = lambda hg, _gd: (grouped_header.copy(), True)
                else:
                    thread._apply_group_assignments = lambda hg, _gd: (hg, False)

                captured_labels = []
                original_set_xlabel = __import__('matplotlib.axes', fromlist=['Axes']).Axes.set_xlabel

                def _capture_set_xlabel(ax, label, *args, **kwargs):
                    captured_labels.append(label)
                    return original_set_xlabel(ax, label, *args, **kwargs)

                with mock.patch('matplotlib.axes.Axes.set_xlabel', new=_capture_set_xlabel):
                    thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)

                self.assertIn(expected_label, captured_labels)

    def test_summary_sheet_trend_uses_dense_labels_without_thinning(self):
        import pandas as pd

        import modules.export_data_thread as export_thread_module
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'trend'}

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05, 10.02],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '1', '2', '2', '3', '3'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        captured = {}
        original_apply_labels = export_thread_module.apply_shared_x_axis_label_strategy
        try:
            def _capture_labels(_ax, labels, **kwargs):
                captured['labels'] = list(labels)
                captured['allow_thinning'] = kwargs.get('allow_thinning')
                return None

            export_thread_module.apply_shared_x_axis_label_strategy = _capture_labels

            thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)
        finally:
            export_thread_module.apply_shared_x_axis_label_strategy = original_apply_labels

        self.assertEqual(captured['labels'], ['1', '1', '2', '2', '3', '3'])
        self.assertFalse(captured['allow_thinning'])


    def test_summary_sheet_distribution_scatter_fallback_draws_only_lsl_usl_reference_lines(self):
        import pandas as pd

        import modules.export_data_thread as export_thread_module
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution'}
        thread.violin_plot_min_samplesize = 10

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05, 10.02],
                'NOM': [10.0] * 6,
                '+TOL': [0.2] * 6,
                '-TOL': [-0.2] * 6,
                'SAMPLE_NUMBER': ['1', '1', '2', '2', '3', '3'],
                'DATE': ['2024-01-01'] * 6,
            }
        )

        captured_calls = []
        original_render_spec_lines = export_thread_module.render_spec_reference_lines
        try:
            def _capture_spec_lines(_ax, nom, lsl, usl, **kwargs):
                captured_calls.append({'nom': nom, 'lsl': lsl, 'usl': usl, 'kwargs': dict(kwargs)})
                return []

            export_thread_module.render_spec_reference_lines = _capture_spec_lines
            thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)
        finally:
            export_thread_module.render_spec_reference_lines = original_render_spec_lines

        self.assertEqual(len(captured_calls), 1)
        self.assertEqual(captured_calls[0]['lsl'], 9.8)
        self.assertEqual(captured_calls[0]['usl'], 10.2)
        self.assertFalse(captured_calls[0]['kwargs'].get('include_nominal', True))


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


    def test_export_filtered_data_loads_dataframe_and_passes_it_to_writer(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(),
            )
            thread = ExportDataThread(request)

            captured = {}

            def fake_writer(df, table_name, excel_writer):
                captured['columns'] = list(df.columns)
                captured['table'] = table_name
                captured['writer_type'] = type(excel_writer).__name__

            thread.write_data_to_excel = fake_writer
            module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
            previous_reader = module.read_sql_dataframe
            module.read_sql_dataframe = lambda *_args, **_kwargs: pd.DataFrame({'ID': [1], 'LABEL': ['A']})
            try:
                thread.export_filtered_data(excel_writer=object())
            finally:
                module.read_sql_dataframe = previous_reader

            self.assertEqual(captured['columns'], ['ID', 'LABEL'])
            self.assertEqual(captured['table'], 'MEASUREMENTS')

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
            thread._export_df_cache = object()
            thread._export_df_column_order = ()

            def fake_export_filtered_data(excel_writer):
                self.assertIsNotNone(excel_writer)
                calls.append('filtered')

            def fake_add_measurements(excel_writer):
                self.assertIsNotNone(excel_writer)
                calls.append('measurements')

            thread.export_filtered_data = fake_export_filtered_data
            thread.add_measurements_horizontal_sheet = fake_add_measurements

            module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe'])
            previous_reader = module.read_sql_dataframe
            module.read_sql_dataframe = lambda *_args, **_kwargs: __import__('pandas').DataFrame()
            try:
                completed = thread.get_export_backend().run(thread)
            finally:
                module.read_sql_dataframe = previous_reader

            self.assertTrue(completed)
            self.assertEqual(calls, ['measurements', 'filtered'])
            self.assertTrue(os.path.exists(out_file))


    def test_run_aborts_pipeline_on_fatal_local_measurement_export_error(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, runner_thread):
                    return runner_thread.run_export_pipeline(excel_writer=object())

            thread.get_export_backend = lambda: _Backend()

            calls = []
            thread.export_filtered_data = lambda *_args, **_kwargs: calls.append('filtered')

            emitted = []
            errors = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: calls.append('finished')
            thread.error_occurred.emit = lambda message: errors.append(message)

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook
            previous_partition_counts = module.fetch_partition_header_counts
            upload_called = {'value': False}
            module.upload_and_convert_workbook = lambda *_args, **_kwargs: upload_called.__setitem__('value', True)
            module.fetch_partition_header_counts = (
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('fatal measurement step failure'))
            )
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload
                module.fetch_partition_header_counts = previous_partition_counts

            self.assertFalse(upload_called['value'])
            self.assertNotIn('filtered', calls)
            self.assertNotIn('finished', calls)
            self.assertFalse(any('Export completed successfully.' in label for label in emitted))
            self.assertTrue(any('Export failed during local workbook generation.' in label for label in emitted))
            self.assertTrue(errors)
            self.assertTrue(any('add_measurements_horizontal_sheet' in message for message in errors))

    def test_google_target_emits_canonical_stage_sequence_on_success(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)
            thread._exported_sheet_names = ['MEASUREMENTS']

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            emitted = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            captured = {}

            def _fake_upload(*_args, **kwargs):
                captured['expected_sheet_names'] = kwargs.get('expected_sheet_names')
                kwargs['status_callback']('uploading')
                kwargs['status_callback']('converting')
                kwargs['status_callback']('validating')
                return GoogleDriveConversionResult(
                    file_id='sheet-id',
                    web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                    local_xlsx_path=out_file,
                    fallback_message=f'Use local .xlsx fallback if needed: {out_file}',
                    warnings=(),
                )

            module.upload_and_convert_workbook = _fake_upload
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            stages = [text.split('\n')[0] for text in emitted if text.split('\n')[0].startswith('Google export stage:')]
            self.assertEqual(
                stages,
                [
                    'Google export stage: generating workbook',
                    'Google export stage: uploading',
                    'Google export stage: converting',
                    'Google export stage: validating',
                    'Google export stage: completed (https://docs.google.com/spreadsheets/d/sheet-id/edit)',
                ],
            )
            self.assertEqual(captured['expected_sheet_names'], ['MEASUREMENTS'])

    def test_google_target_passes_expected_sheet_names_in_export_order(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)
            thread._exported_sheet_names = ['REF_A', 'REF_A_summary', 'REF_B', 'REF_B_summary', 'MEASUREMENTS']

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            captured = {}
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _fake_upload(*_args, **kwargs):
                captured['expected_sheet_names'] = kwargs.get('expected_sheet_names')
                return GoogleDriveConversionResult(
                    file_id='sheet-id',
                    web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                    local_xlsx_path=out_file,
                    fallback_message=f'Use local .xlsx fallback if needed: {out_file}',
                    warnings=(),
                )

            module.upload_and_convert_workbook = _fake_upload
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            self.assertEqual(
                captured['expected_sheet_names'],
                ['REF_A', 'REF_A_summary', 'REF_B', 'REF_B_summary', 'MEASUREMENTS'],
            )

    def test_google_target_emits_retry_stage_message_before_completion(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            emitted = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _fake_upload(*_args, **kwargs):
                kwargs['status_callback']('uploading')
                kwargs['status_callback']('uploading retry 2/3, elapsed 01:20: temporary network issue')
                kwargs['status_callback']('converting')
                kwargs['status_callback']('validating')
                return GoogleDriveConversionResult(
                    file_id='sheet-id',
                    web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                    local_xlsx_path=out_file,
                    fallback_message=f'Use local .xlsx fallback if needed: {out_file}',
                    warnings=(),
                )

            module.upload_and_convert_workbook = _fake_upload
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            retry_messages = [text for text in emitted if 'uploading retry' in text]
            self.assertEqual(len(retry_messages), 1)
            self.assertIn('Google export stage: uploading (uploading retry 2/3, elapsed 01:20: temporary network issue)', retry_messages[0])
            stages = [text.split('\n')[0] for text in emitted if text.split('\n')[0].startswith('Google export stage:')]
            self.assertEqual(stages[-1], 'Google export stage: completed (https://docs.google.com/spreadsheets/d/sheet-id/edit)')


    def test_google_target_cancellation_error_treated_as_user_cancel(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            canceled_calls = []
            finished_calls = []
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.canceled.emit = lambda: canceled_calls.append('canceled')
            thread.finished.emit = lambda: finished_calls.append('finished')

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _raise_canceled(*_args, **_kwargs):
                raise module.GoogleDriveCanceledError('Google export canceled by user.')

            module.upload_and_convert_workbook = _raise_canceled
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            self.assertEqual(canceled_calls, ['canceled'])
            self.assertEqual(finished_calls, [])
            self.assertEqual(thread.completion_metadata.get('fallback_message', ''), '')

    def test_google_target_auth_fallback_skips_error_logging(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            emitted = []
            finished_calls = []
            logger_calls = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: finished_calls.append('finished')
            thread.log_and_exit = lambda exc: logger_calls.append(str(exc))

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _raise_auth_error(*_args, **_kwargs):
                raise module.GoogleDriveAuthError('Missing token.json for Google Drive export. Please complete OAuth authorization first.')

            module.upload_and_convert_workbook = _raise_auth_error
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            self.assertEqual(finished_calls, ['finished'])
            self.assertEqual(logger_calls, [])
            self.assertIn('fallback_message', thread.completion_metadata)
            self.assertIn('using local .xlsx fallback', thread.completion_metadata['fallback_message'])
            stages = [text.split('\n')[0] for text in emitted if text.split('\n')[0].startswith('Google export stage:')]
            self.assertIn('Google export stage: fallback (', stages[-1])
            self.assertIn(f'Google export failed; using local .xlsx fallback: {out_file}', stages[-1])

    def test_google_target_final_fallback_is_non_crashing_and_emits_fallback_stage(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            emitted = []
            finished_calls = []
            logger_calls = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: finished_calls.append('finished')
            thread.log_and_exit = lambda exc: logger_calls.append(str(exc))

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _raise_transient(*_args, **_kwargs):
                raise module.GoogleDriveExportError('temporary outage')

            module.upload_and_convert_workbook = _raise_transient
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            self.assertEqual(finished_calls, ['finished'])
            self.assertEqual(logger_calls, [])
            self.assertIn('fallback_message', thread.completion_metadata)
            self.assertIn('using local .xlsx fallback', thread.completion_metadata['fallback_message'])
            stages = [text.split('\n')[0] for text in emitted if text.split('\n')[0].startswith('Google export stage:')]
            self.assertIn('Google export stage: fallback (', stages[-1])
            self.assertIn(f'Google export failed; using local .xlsx fallback: {out_file}', stages[-1])

    def test_google_target_run_keeps_xlsx_fallback_and_conversion_warnings(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)
            thread._exported_sheet_names = ['REF_A', 'MEASUREMENTS']

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()

            emitted = []
            thread.update_label.emit = lambda text: emitted.append(text)
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook
            module.upload_and_convert_workbook = lambda *_args, **_kwargs: GoogleDriveConversionResult(
                file_id='sheet-id',
                web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                local_xlsx_path=out_file,
                fallback_message=f'Conversion completed with warnings. Use local .xlsx fallback if needed: {out_file}',
                warnings=('chart patch skipped for one chart',),
            )
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            self.assertEqual(thread.completion_metadata['converted_file_id'], 'sheet-id')
            self.assertEqual(thread.completion_metadata['converted_url'], 'https://docs.google.com/spreadsheets/d/sheet-id/edit')
            self.assertEqual(thread.completion_metadata['local_xlsx_path'], out_file)
            self.assertEqual(thread.completion_metadata['conversion_warnings'][0], 'chart patch skipped for one chart')
            self.assertEqual(thread.completion_metadata['conversion_warning_details'], [])
            self.assertEqual(thread.completion_metadata['converted_tab_titles'], [])
            fallback_stage_messages = [text for text in emitted if text.split('\n')[0].startswith('Google export stage: fallback')]
            self.assertTrue(fallback_stage_messages)
            self.assertIn(out_file, fallback_stage_messages[0])


    def test_google_conversion_stage_logging_is_deterministic_on_success(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _fake_upload(*_args, **kwargs):
                kwargs['status_callback']('uploading')
                kwargs['status_callback']('converting')
                kwargs['status_callback']('validating')
                return GoogleDriveConversionResult(
                    file_id='sheet-id',
                    web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                    local_xlsx_path=out_file,
                    fallback_message=f'Use local .xlsx fallback if needed: {out_file}',
                    warnings=(),
                )

            module.upload_and_convert_workbook = _fake_upload
            logger = logging.getLogger()
            previous_handlers = list(logger.handlers)
            previous_level = logger.level
            records = []

            class _ListHandler(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = _ListHandler()
            logger.handlers = [handler]
            logger.setLevel(logging.INFO)
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload
                logger.handlers = previous_handlers
                logger.setLevel(previous_level)

            stage_messages = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith('Google conversion stage')
            ]
            self.assertEqual(
                stage_messages,
                [
                    'Google conversion stage',
                    'Google conversion stage',
                    'Google conversion stage',
                ],
            )

    def test_google_conversion_stage_logging_includes_retry_attempt_context(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _fake_upload(*_args, **kwargs):
                kwargs['status_callback']('uploading')
                kwargs['status_callback']('uploading retry 2/3, elapsed 01:20: temporary network issue')
                kwargs['status_callback']('uploading')
                kwargs['status_callback']('converting')
                kwargs['status_callback']('validating')
                return GoogleDriveConversionResult(
                    file_id='sheet-id',
                    web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                    local_xlsx_path=out_file,
                    fallback_message=f'Use local .xlsx fallback if needed: {out_file}',
                    warnings=(),
                )

            module.upload_and_convert_workbook = _fake_upload
            logger = logging.getLogger()
            previous_handlers = list(logger.handlers)
            previous_level = logger.level
            records = []

            class _ListHandler(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = _ListHandler()
            logger.handlers = [handler]
            logger.setLevel(logging.INFO)
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload
                logger.handlers = previous_handlers
                logger.setLevel(previous_level)

            stage_messages = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith('Google conversion stage')
            ]
            self.assertEqual(
                stage_messages,
                [
                    'Google conversion stage',
                    'Google conversion stage (attempt 2/3)',
                    'Google conversion stage',
                    'Google conversion stage',
                ],
            )
            retry_warning_messages = [
                record.getMessage()
                for record in records
                if record.getMessage().startswith('Google conversion upload retry')
            ]
            self.assertEqual(retry_warning_messages, ['Google conversion upload retry'])

    def test_google_target_warning_logs_issue_details(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)
            thread._exported_sheet_names = ['REF_A', 'MEASUREMENTS']

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook
            module.upload_and_convert_workbook = lambda *_args, **_kwargs: GoogleDriveConversionResult(
                file_id='sheet-id',
                web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                local_xlsx_path=out_file,
                fallback_message=f'Conversion completed with warnings. Use local .xlsx fallback if needed: {out_file}',
                warnings=('chart patch skipped for one chart',),
            )
            logger = logging.getLogger()
            previous_handlers = list(logger.handlers)
            previous_level = logger.level
            records = []

            class _ListHandler(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = _ListHandler()
            logger.handlers = [handler]
            logger.setLevel(logging.WARNING)
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload
                logger.handlers = previous_handlers
                logger.setLevel(previous_level)

            warning_messages = [record.getMessage() for record in records if record.levelno >= logging.WARNING]
            self.assertTrue(any('Google export issue: conversion completed with warnings' in msg for msg in warning_messages))
            self.assertTrue(any('fallback=Conversion completed with warnings.' in msg for msg in warning_messages))
            self.assertTrue(any('warnings=chart patch skipped for one chart' in msg for msg in warning_messages))

    def test_google_target_success_metadata_contains_expected_keys(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)
            thread._exported_sheet_names = ['MEASUREMENTS']

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook
            module.upload_and_convert_workbook = lambda *_args, **_kwargs: GoogleDriveConversionResult(
                file_id='sheet-id',
                web_url='https://docs.google.com/spreadsheets/d/sheet-id/edit',
                local_xlsx_path=out_file,
                fallback_message='',
                warnings=(),
            )
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            metadata = thread.completion_metadata
            self.assertEqual(metadata['converted_url'], 'https://docs.google.com/spreadsheets/d/sheet-id/edit')
            self.assertEqual(metadata['fallback_message'], '')
            self.assertEqual(metadata['conversion_warnings'], [])

    def test_google_target_exception_fallback_metadata_contains_expected_keys(self):
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, 'out.xlsx')
            request = ExportRequest(
                paths=AppPaths(db_file='test.db', excel_file=out_file),
                options=ExportOptions(export_target='google_sheets_drive_convert'),
            )
            thread = ExportDataThread(request)

            class _Backend:
                def run(self, _thread):
                    return True

            thread.get_export_backend = lambda: _Backend()
            thread.update_label.emit = lambda *_: None
            thread.update_progress.emit = lambda *_: None
            thread.finished.emit = lambda: None
            thread.log_and_exit = lambda *_: None

            module = __import__('modules.export_data_thread', fromlist=['upload_and_convert_workbook'])
            previous_upload = module.upload_and_convert_workbook

            def _raise_export_error(*_args, **_kwargs):
                raise module.GoogleDriveExportError('temporary outage')

            module.upload_and_convert_workbook = _raise_export_error
            try:
                thread.run()
            finally:
                module.upload_and_convert_workbook = previous_upload

            metadata = thread.completion_metadata
            self.assertEqual(metadata.get('converted_url'), None)
            self.assertIn(f'Google export failed; using local .xlsx fallback: {out_file}', metadata['fallback_message'])
            self.assertEqual(metadata['conversion_warnings'], ['temporary outage'])



    def test_summary_sheet_grouped_violin_and_iqr_labels_include_sample_counts(self):
        import pandas as pd

        import modules.export_data_thread as export_thread_module
        from modules.contracts import AppPaths, ExportOptions, ExportRequest

        class _FakeSummaryWorksheet:
            def write(self, *_args, **_kwargs):
                return None

            def insert_image(self, *_args, **_kwargs):
                return None

        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(generate_summary_sheet=True),
        )
        thread = ExportDataThread(request)
        thread._optimization_toggles['summary_sheet_minimum_charts'] = {'distribution', 'iqr'}
        thread.violin_plot_min_samplesize = 2

        header_group = pd.DataFrame(
            {
                'MEAS': [9.95, 10.0, 10.2, 10.1, 10.05],
                'NOM': [10.0] * 5,
                '+TOL': [0.2] * 5,
                '-TOL': [-0.2] * 5,
                'SAMPLE_NUMBER': ['1', '2', '3', '4', '5'],
                'DATE': ['2024-01-01'] * 5,
            }
        )
        grouped_header = header_group.assign(GROUP=['A', 'A', 'B', 'B', 'B'])
        thread._prepared_grouping_df = pd.DataFrame()
        thread._apply_group_assignments = lambda hg, _gd: (grouped_header.copy(), True)

        captured = {}
        original_render_violin = export_thread_module.render_violin
        original_render_iqr_boxplot = export_thread_module.render_iqr_boxplot
        try:
            def _capture_violin(_ax, _values, labels, **_kwargs):
                captured['violin_labels'] = list(labels)
                return None

            def _capture_iqr(_ax, _values, labels):
                captured['iqr_labels'] = list(labels)
                return None

            export_thread_module.render_violin = _capture_violin
            export_thread_module.render_iqr_boxplot = _capture_iqr

            thread.summary_sheet_fill(_FakeSummaryWorksheet(), 'H1', header_group, col=5)
        finally:
            export_thread_module.render_violin = original_render_violin
            export_thread_module.render_iqr_boxplot = original_render_iqr_boxplot

        self.assertEqual(captured['violin_labels'], ['A (n=2)', 'B (n=3)'])
        self.assertEqual(captured['iqr_labels'], ['A (n=2)', 'B (n=3)'])


if __name__ == '__main__':
    unittest.main()

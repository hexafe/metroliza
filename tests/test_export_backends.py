import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import zipfile

from modules.export_backends import ExcelExportBackend, HtmlDashboardExportBackend
from metroliza.exporting.execution import ExportOutcomeKind, ExportStageOutcome


class _WorkbookCloseNotifications:
    def begin_workbook_close(self):
        self.close_started = True

    def complete_workbook_close(self, elapsed):
        self.close_elapsed = elapsed


class TestExcelExportBackend(unittest.TestCase):
    def test_structured_warning_outcome_remains_successful(self):
        outcome = ExportStageOutcome.completed_with_warnings("Dashboard snapshot skipped")

        self.assertTrue(outcome)
        self.assertEqual(outcome.kind, ExportOutcomeKind.COMPLETED_WITH_WARNINGS)
        self.assertEqual(outcome.warnings, ("Dashboard snapshot skipped",))

    def test_create_writer_enables_safe_imported_string_policy(self):
        backend = ExcelExportBackend()

        with patch('modules.export_backends.xlsxwriter.Workbook') as mock_writer:
            backend.create_writer('out.xlsx')

        mock_writer.assert_called_once_with(
            'out.xlsx',
            {
                'nan_inf_to_errors': True,
                'strings_to_formulas': False,
                'strings_to_urls': False,
            },
        )

    def test_untrusted_headers_and_values_are_literal_strings(self):
        backend = ExcelExportBackend()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / 'literal-values.xlsx'
            writer = backend.create_writer(str(output_path))
            backend.write_dataframe(
                writer,
                ([('=1+1', '+2', '-3', '@cmd', 'https://example.invalid')], ['=HEADER']),
                'Data',
            )
            backend.close_writer(writer)

            with zipfile.ZipFile(output_path) as workbook_zip:
                worksheet_xml = workbook_zip.read('xl/worksheets/sheet1.xml').decode('utf-8')

        self.assertNotIn('<f>', worksheet_xml)
        self.assertNotIn('<hyperlink', worksheet_xml)

    def test_run_replaces_target_only_after_successful_close(self):
        class _Backend(ExcelExportBackend):
            def create_writer(self, excel_file):
                return excel_file

            def close_writer(self, writer):
                Path(writer).write_text('new workbook', encoding='utf-8')

        class _Thread(_WorkbookCloseNotifications):
            def __init__(self, excel_file):
                self.excel_file = excel_file
                self.writer_path = None

            def run_export_pipeline(self, excel_writer):
                self.writer_path = excel_writer
                self.target_during_pipeline = Path(self.excel_file).read_text(encoding='utf-8')
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / 'export.xlsx'
            target_path.write_text('old workbook', encoding='utf-8')
            thread = _Thread(str(target_path))

            outcome = _Backend().run(thread)

            self.assertEqual(outcome, ExportStageOutcome.completed())

            self.assertNotEqual(Path(thread.writer_path), target_path)
            self.assertEqual(thread.target_during_pipeline, 'old workbook')
            self.assertEqual(target_path.read_text(encoding='utf-8'), 'new workbook')
            self.assertFalse(Path(thread.writer_path).exists())
            self.assertTrue(thread.close_started)
            self.assertGreaterEqual(thread.close_elapsed, 0.0)

    def test_run_deletes_temp_and_preserves_target_when_pipeline_cancels(self):
        class _Backend(ExcelExportBackend):
            def create_writer(self, excel_file):
                return excel_file

            def close_writer(self, writer):
                Path(writer).write_text('partial workbook', encoding='utf-8')

        class _Thread(_WorkbookCloseNotifications):
            def __init__(self, excel_file):
                self.excel_file = excel_file
                self.writer_path = None

            def run_export_pipeline(self, excel_writer):
                self.writer_path = excel_writer
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / 'export.xlsx'
            target_path.write_text('old workbook', encoding='utf-8')
            thread = _Thread(str(target_path))

            outcome = _Backend().run(thread)

            self.assertEqual(outcome.kind, ExportOutcomeKind.CANCELED)

            self.assertEqual(target_path.read_text(encoding='utf-8'), 'old workbook')
            self.assertFalse(Path(thread.writer_path).exists())

    def test_run_deletes_temp_and_preserves_target_on_pipeline_error(self):
        class _Backend(ExcelExportBackend):
            def create_writer(self, excel_file):
                return excel_file

            def close_writer(self, writer):
                Path(writer).write_text('partial workbook', encoding='utf-8')

        class _Thread(_WorkbookCloseNotifications):
            def __init__(self, excel_file):
                self.excel_file = excel_file
                self.writer_path = None

            def run_export_pipeline(self, excel_writer):
                self.writer_path = excel_writer
                raise RuntimeError('boom')

        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / 'export.xlsx'
            target_path.write_text('old workbook', encoding='utf-8')
            thread = _Thread(str(target_path))

            with self.assertRaisesRegex(RuntimeError, 'boom'):
                _Backend().run(thread)

            self.assertEqual(target_path.read_text(encoding='utf-8'), 'old workbook')
            self.assertFalse(Path(thread.writer_path).exists())


class TestHtmlDashboardExportBackend(unittest.TestCase):
    def test_run_invokes_dashboard_pipeline_without_creating_workbook(self):
        backend = HtmlDashboardExportBackend()

        class _Thread:
            def __init__(self):
                self.html_dashboard_file = ''
                self.writer = None

            def run_html_dashboard_pipeline(self, writer):
                self.writer = writer
                writer.workbook.add_worksheet('Summary')
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / 'dashboard.html'
            thread = _Thread()
            thread.html_dashboard_file = str(target_path)

            self.assertTrue(backend.run(thread))

            self.assertIsNotNone(thread.writer)
            self.assertEqual(backend.list_sheet_names(thread.writer), {'Summary'})
            self.assertFalse(target_path.with_suffix('.xlsx').exists())


if __name__ == '__main__':
    unittest.main()

import unittest
import tempfile
import time
import io
from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from unittest.mock import patch
import zipfile
import pytest

from modules.export_backends import ExcelExportBackend, HtmlDashboardExportBackend
from metroliza.exporting.execution import ExportOutcomeKind, ExportStageOutcome
from metroliza.exporting.output_publication import OutputConsent
from metroliza.exporting import xlsx_parallel_package as packaging
from xlsxwriter.contenttypes import ContentTypes


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

            thread.replace_outputs = (OutputConsent.for_path(target_path),)
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


# Real writer disposal is tested separately from the lightweight lifecycle doubles.
@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('memory_mode', ['normal', 'constant', 'in_memory'])
@pytest.mark.parametrize('existing_target', [False, True])
def test_aborted_real_writer_does_not_serialize_or_leave_temporary_files(
    tmp_path, monkeypatch, failure, memory_mode, existing_target,
):
    target = tmp_path / 'export.xlsx'
    if existing_target:
        target.write_bytes(b'previous output')
    backend = ExcelExportBackend()
    create_writer = backend.create_writer
    writers = []

    def create(path):
        writer = create_writer(path)
        writer.book.constant_memory = memory_mode == 'constant'
        writer.book.in_memory = memory_mode == 'in_memory'
        writers.append(writer)
        return writer

    monkeypatch.setattr(backend, 'create_writer', create)

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(target)

        def run_export_pipeline(self, writer):
            sheet = writer.book.add_worksheet('Partial')
            for i in range(2000):
                sheet.write_row(i, 0, [i, 'cancelled synthetic data'])
            self.abort_marker = time.monotonic()
            if failure:
                raise RuntimeError('pipeline failed')
            return False

    def must_not_prepare(*args):
        raise AssertionError('cancel/failure attempted workbook serialization')

    monkeypatch.setattr(packaging.Workbook, '_prepare_sst_string_data', must_not_prepare)
    thread = Thread()
    if failure:
        with pytest.raises(RuntimeError, match='pipeline failed'):
            backend.run(thread)
    else:
        assert not backend.run(thread)
    assert time.monotonic() - thread.abort_marker < 2.0
    assert thread.close_started
    assert thread.close_elapsed < 2.0
    assert sorted(path.name for path in tmp_path.iterdir()) == (['export.xlsx'] if existing_target else [])
    if existing_target:
        assert target.read_bytes() == b'previous output'
    assert writers[0].book.fileclosed
    for sheet in writers[0].book.worksheets():
        if sheet.constant_memory:
            assert sheet.row_data_fh.closed


@pytest.mark.parametrize('unsupported', [False, True])
def test_packaging_failure_preserves_target_and_cleans_owned_scratch(tmp_path, monkeypatch, unsupported):
    target = tmp_path / 'export.xlsx'
    target.write_bytes(b'previous output')
    if unsupported:
        monkeypatch.setattr(packaging, '_STORE_DIGEST', 'unsupported')
    monkeypatch.setattr(packaging, '_MIN_MEMBER_BYTES', 1)
    archive_class = zipfile.ZipFile if unsupported else packaging._PreparedZipFile
    original_write = archive_class.write
    calls = []

    def fail_second_member(self, *args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise OSError('injected member failure')
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(archive_class, 'write', fail_second_member)

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(target)

        def run_export_pipeline(self, writer):
            writer.book.add_worksheet().write(0, 0, 'Synthetic')
            return True

    with pytest.raises(packaging.xlsxwriter.exceptions.FileCreateError, match='injected member failure'):
        ExcelExportBackend().run(Thread())
    assert len(calls) == 2
    assert target.read_bytes() == b'previous output'
    assert [path.name for path in tmp_path.iterdir()] == ['export.xlsx']


@pytest.mark.parametrize('serializer', [ContentTypes, packaging.Theme])
@pytest.mark.parametrize('stock', [False, True])
def test_retained_serializer_error_closes_before_delete(tmp_path, monkeypatch, serializer, stock):
    if stock:
        monkeypatch.setattr(packaging, '_STORE_DIGEST', 'stock fallback')
    target = tmp_path / 'export.xlsx'
    target.write_bytes(b'previous output')
    failure = RuntimeError('retained serializer failure')
    handles, deletion_states = [], []

    def fault(self):
        handles.append(self.fh)
        raise failure

    monkeypatch.setattr(serializer, '_assemble_xml_file', fault)
    unlink = Path.unlink
    cleanup = tempfile.TemporaryDirectory.cleanup

    def checked_unlink(path, *args, **kwargs):
        deletion_states.append(all(handle.closed for handle in handles))
        return unlink(path, *args, **kwargs)

    def checked_cleanup(directory):
        deletion_states.append(all(handle.closed for handle in handles))
        return cleanup(directory)

    monkeypatch.setattr(Path, 'unlink', checked_unlink)
    monkeypatch.setattr(tempfile.TemporaryDirectory, 'cleanup', checked_cleanup)

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(target)

        def run_export_pipeline(self, writer):
            writer.book.add_worksheet().write(0, 0, 'Synthetic')
            return True

    with pytest.raises(RuntimeError) as caught:
        ExcelExportBackend().run(Thread())
    assert caught.value is failure
    names, cursor = [], failure.__traceback__
    while cursor is not None:
        names.append(cursor.tb_frame.f_code.co_name)
        cursor = cursor.tb_next
    assert 'fault' in names and '_store_workbook' in names
    assert handles and all(handle.closed for handle in handles)
    assert deletion_states and all(deletion_states)
    archives = [value for value in packaging._exception_locals(failure) if isinstance(value, zipfile.ZipFile)]
    assert archives and all(archive.fp is None for archive in archives)
    assert target.read_bytes() == b'previous output'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('secondary', ['close', 'unlink', 'rmtree'])
def test_cleanup_secondary_failure_keeps_original_exception(tmp_path, monkeypatch, secondary):
    failure = RuntimeError('original serialization failure')
    raised = []

    class CloseFailure(io.IOBase):
        def __init__(self, handle):
            self.handle = handle

        @property
        def name(self):
            return self.handle.name

        @property
        def closed(self):
            return self.handle.closed

        def close(self):
            if not self.handle.closed:
                self.handle.close()
                raise OSError('secondary close failure')

    def fault(self):
        if secondary == 'close':
            self.fh = CloseFailure(self.fh)
        raise failure

    monkeypatch.setattr(ContentTypes, '_assemble_xml_file', fault)
    owner, attribute = (Path, 'unlink') if secondary == 'unlink' else (tempfile.TemporaryDirectory, 'cleanup')
    original = getattr(owner, attribute)

    def fail_once(*args, **kwargs):
        if not raised:
            raised.append(True)
            raise OSError(f'secondary {secondary} failure')
        return original(*args, **kwargs)

    if secondary != 'close':
        monkeypatch.setattr(owner, attribute, fail_once)

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(tmp_path / 'output.xlsx')

        def run_export_pipeline(self, writer):
            writer.book.add_worksheet().write(0, 0, 'Synthetic')
            return True

    with pytest.raises(RuntimeError) as caught:
        ExcelExportBackend().run(Thread())
    assert caught.value is failure
    assert failure.__traceback__ is not None
    assert any(f'secondary {secondary} failure' in note for note in failure.__notes__)
    assert not list(tmp_path.iterdir())


def test_binary_image_write_failure_closes_direct_packager_handle(tmp_path):
    failure = RuntimeError('image stream failure')

    class ImageData(io.BytesIO):
        armed = False

        def getvalue(self):
            if self.armed:
                raise failure
            return super().getvalue()

    data = ImageData(b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII='))

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(tmp_path / 'output.xlsx')

        def run_export_pipeline(self, writer):
            writer.book.add_worksheet().insert_image('A1', 'synthetic.png', {'image_data': data})
            data.armed = True
            return True

    with pytest.raises(RuntimeError) as caught:
        ExcelExportBackend().run(Thread())
    assert caught.value is failure
    cursor, handles = failure.__traceback__, []
    while cursor is not None:
        if cursor.tb_frame.f_code.co_name == '_add_image_files':
            handles.append(cursor.tb_frame.f_locals['os_file'])
        cursor = cursor.tb_next
    assert handles and all(handle.closed for handle in handles)
    assert not data.closed
    assert not list(tmp_path.iterdir())


def test_failing_writer_does_not_close_concurrent_writer(tmp_path, monkeypatch):
    original = ContentTypes._assemble_xml_file
    b_open, a_done = Event(), Event()
    b_handles = []
    failure = RuntimeError('writer A failed')

    def serialize(self):
        if b_open.is_set():
            foreign_handle = b_handles[0]
            assert not foreign_handle.closed
            raise failure
        b_handles.append(self.fh)
        b_open.set()
        assert a_done.wait(10)
        return original(self)

    monkeypatch.setattr(ContentTypes, '_assemble_xml_file', serialize)

    class Thread(_WorkbookCloseNotifications):
        def __init__(self, name):
            self.excel_file = str(tmp_path / name)

        def run_export_pipeline(self, writer):
            writer.book.add_worksheet().write(0, 0, 'Synthetic')
            return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        b = pool.submit(ExcelExportBackend().run, Thread('b.xlsx'))
        assert b_open.wait(10)
        try:
            with pytest.raises(RuntimeError) as caught:
                ExcelExportBackend().run(Thread('a.xlsx'))
            assert caught.value is failure
            assert not b_handles[0].closed
        finally:
            a_done.set()
        assert b.result(timeout=10)
    assert not (tmp_path / 'a.xlsx').exists()
    with zipfile.ZipFile(tmp_path / 'b.xlsx') as archive:
        assert archive.testzip() is None


@pytest.mark.parametrize('secondary', ['close', 'unlink', 'rmtree'])
def test_pipeline_error_survives_fail_once_disposal(tmp_path, monkeypatch, secondary):
    target = tmp_path / 'export.xlsx'
    target.write_bytes(b'previous output')
    failure = RuntimeError('initiating pipeline error')
    injected, writers, serialization = [], [], []
    backend = ExcelExportBackend()
    create = backend.create_writer

    def create_constant_memory(path):
        writer = create(path)
        writer.book.constant_memory = True
        writers.append(writer)
        return writer

    monkeypatch.setattr(backend, 'create_writer', create_constant_memory)

    class CloseOnce(io.IOBase):
        def __init__(self, handle):
            self.handle = handle

        @property
        def name(self):
            return self.handle.name

        @property
        def closed(self):
            return self.handle.closed

        def close(self):
            if not injected:
                injected.append('close')
                raise OSError('secondary close failure')
            self.handle.close()

    owner, attribute = (Path, 'unlink') if secondary == 'unlink' else (tempfile.TemporaryDirectory, 'cleanup')
    original = getattr(owner, attribute)

    def fail_once(*args, **kwargs):
        if not injected:
            injected.append(secondary)
            raise OSError(f'secondary {secondary} failure')
        return original(*args, **kwargs)

    if secondary != 'close':
        monkeypatch.setattr(owner, attribute, fail_once)

    def must_not_serialize(*args):
        serialization.append(True)
        raise AssertionError('pipeline exception attempted serialization')

    monkeypatch.setattr(packaging.Workbook, '_prepare_sst_string_data', must_not_serialize)

    class Thread(_WorkbookCloseNotifications):
        excel_file = str(target)

        def run_export_pipeline(self, writer):
            sheet = writer.book.add_worksheet('Partial')
            for i in range(2000):
                sheet.write_row(i, 0, [i, 'synthetic pipeline data'])
            if secondary == 'close':
                sheet.row_data_fh = CloseOnce(sheet.row_data_fh)
            raise failure

    with pytest.raises(Exception) as caught:
        backend.run(Thread())
    assert injected == [secondary]
    assert caught.value is failure
    cursor, origin = failure.__traceback__, []
    while cursor is not None:
        origin.append(cursor.tb_frame.f_code.co_name)
        cursor = cursor.tb_next
    assert 'run_export_pipeline' in origin
    assert any(f'secondary {secondary} failure' in note for note in failure.__notes__)
    assert not serialization
    assert target.read_bytes() == b'previous output'
    assert list(tmp_path.iterdir()) == [target]
    assert writers[0].book.fileclosed
    assert all(sheet.row_data_fh.closed for sheet in writers[0].book.worksheets())

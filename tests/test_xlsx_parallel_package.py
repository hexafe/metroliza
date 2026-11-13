"""Strict synthetic package controls for the XLSX close implementation."""

from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
from pathlib import Path
import zipfile
import zlib
import weakref

import openpyxl
import pytest
import xlsxwriter

from metroliza.exporting.export_backends import ExcelExportBackend, XlsxWorkbookWriter
from metroliza.exporting.xlsx_bulk_sheet import enable_bulk_rows
from metroliza.exporting.xlsx_writer_policy import xlsxwriter_workbook_options
from metroliza.exporting import xlsx_parallel_package as packaging


def _writer(path, *, stock, options=None):
    backend = ExcelExportBackend()
    if not stock and not options:
        return backend.create_writer(str(path))
    book = xlsxwriter.Workbook(str(path), {**xlsxwriter_workbook_options(), **(options or {})})
    enable_bulk_rows(book)
    if not stock:
        packaging.enable_parallel_package(book)
    return XlsxWorkbookWriter(path=str(path), book=book, sheets={})


def _populate(writer, scenario):
    backend = ExcelExportBackend()
    book = writer.book
    book.set_properties({'created': datetime(2020, 1, 2, 3, 4, 5)})
    if scenario == 'empty':
        return
    sheets = ['Measurements', 'Summary'] if scenario == 'main' else ['Summary']
    if scenario == 'extended':
        sheets = ['Group A', 'Group B', 'Summary']
    for sheet_name in sheets:
        rows = [(i, i / 8, f'value-{i % 37}', '=literal', 'https://example.invalid')
                for i in range(4000)]
        backend.write_dataframe(writer, (rows, ['Index', 'Value', 'Label', 'Formula', 'URL']), sheet_name)
        sheet = writer.sheets[sheet_name]
        sheet.freeze_panes(1, 0)
        sheet.set_column(0, 4, 18)
        sheet.write_comment(0, 0, 'Synthetic package control')
        sheet.print_area(0, 0, 20, 4)
        chart = book.add_chart({'type': 'line'})
        chart.add_series({'values': [sheet_name, 1, 1, 20, 1]})
        sheet.insert_chart('G2', chart)
    if scenario == 'csv':
        writer.sheets['Summary'].autofilter(0, 0, 4000, 4)


def _assert_packages_equal(left, right):
    with zipfile.ZipFile(left) as a, zipfile.ZipFile(right) as b:
        assert a.testzip() is None
        assert b.testzip() is None
        assert a.namelist() == b.namelist()
        for ai, bi in zip(a.infolist(), b.infolist(), strict=True):
            assert ai.CRC == bi.CRC, ai.filename
            assert a.read(ai) == b.read(bi), ai.filename
            assert (ai.date_time, ai.external_attr, ai.compress_type, ai.file_size) == (
                bi.date_time, bi.external_attr, bi.compress_type, bi.file_size)
    assert Path(left).read_bytes() == Path(right).read_bytes()
    for path in (left, right):
        loaded = openpyxl.load_workbook(path)
        try:
            assert loaded.sheetnames
        finally:
            loaded.close()


@pytest.mark.parametrize('scenario', ['main', 'extended', 'csv', 'empty'])
def test_stock_package_equivalence(tmp_path, scenario):
    """Written and observed on production before the packaging hook was added."""
    paths = [tmp_path / f'{scenario}-{kind}.xlsx' for kind in ('stock', 'backend')]
    for path, stock in zip(paths, (True, False), strict=True):
        writer = _writer(path, stock=stock)
        _populate(writer, scenario)
        if stock:
            writer.book.close()
        else:
            ExcelExportBackend().close_writer(writer)
    _assert_packages_equal(*paths)


@pytest.mark.parametrize('mutation', ['bytes', 'order', 'missing'])
def test_package_comparator_rejects_changes(tmp_path, mutation):
    paths = [tmp_path / 'a.xlsx', tmp_path / 'b.xlsx']
    with zipfile.ZipFile(paths[0], 'w') as archive:
        archive.writestr('a', b'first')
        archive.writestr('b', b'second')
    entries = [('a', b'first'), ('b', b'second')]
    if mutation == 'bytes':
        entries[1] = ('b', b'changed')
    elif mutation == 'order':
        entries.reverse()
    else:
        entries.pop()
    with zipfile.ZipFile(paths[1], 'w') as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    with pytest.raises(AssertionError):
        _assert_packages_equal(*paths)


@pytest.mark.parametrize('fallback', ['version', 'interface', 'zip_interface', 'state', 'setup', 'deflate'])
def test_stock_fallback_does_not_prepare_twice(tmp_path, monkeypatch, fallback):
    paths = [tmp_path / 'stock.xlsx', tmp_path / 'fallback.xlsx']
    stock = _writer(paths[0], stock=True)
    _populate(stock, 'extended')
    stock.book.close()
    if fallback == 'version':
        monkeypatch.setattr(xlsxwriter, '__version__', 'unsupported')
    elif fallback == 'interface':
        monkeypatch.setattr(packaging, '_STORE_DIGEST', 'unsupported')
    elif fallback == 'zip_interface':
        monkeypatch.setattr(packaging, '_ZIP_DIGESTS', ())
    elif fallback == 'state':
        monkeypatch.setattr(packaging, '_PackageState', lambda *args: (_ for _ in ()).throw(RuntimeError('state')))
    elif fallback == 'setup':
        monkeypatch.setattr(packaging, 'FunctionType', lambda *args: (_ for _ in ()).throw(RuntimeError('setup')))
    else:
        monkeypatch.setattr(packaging, '_deflate', lambda *args: (_ for _ in ()).throw(RuntimeError('deflate')))
    writer = _writer(paths[1], stock=False)
    _populate(writer, 'extended')
    calls = []
    original = writer.book._prepare_drawings

    def prepare_once():
        calls.append('prepare')
        return original()

    writer.book._prepare_drawings = prepare_once
    ExcelExportBackend().close_writer(writer)
    assert calls == ['prepare']
    _assert_packages_equal(*paths)
    assert sorted(path.name for path in tmp_path.iterdir()) == ['fallback.xlsx', 'stock.xlsx']


def test_binary_image_member_is_literal_stock_bytes(tmp_path):
    paths = [tmp_path / 'stock.xlsx', tmp_path / 'backend.xlsx']
    for path, stock in zip(paths, (True, False), strict=True):
        writer = _writer(path, stock=stock)
        writer.book.set_properties({'created': datetime(2020, 1, 2)})
        sheet = writer.book.add_worksheet()
        png = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=')
        sheet.insert_image('A1', 'synthetic.png', {'image_data': io.BytesIO(png)})
        ExcelExportBackend().close_writer(writer)
    _assert_packages_equal(*paths)


@pytest.mark.parametrize('options', [{'in_memory': True}, {'constant_memory': True}])
def test_memory_modes_preserve_stock_output_and_cleanup(tmp_path, options):
    paths = [tmp_path / 'stock.xlsx', tmp_path / 'backend.xlsx']
    for path, stock in zip(paths, (True, False), strict=True):
        writer = _writer(path, stock=stock, options={**options, 'tmpdir': str(tmp_path)})
        writer.book.set_properties({'created': datetime(2020, 1, 2)})
        sheet = writer.book.add_worksheet('Data')
        for i in range(5000):
            sheet.write_row(i, 0, [i, f'row-{i}', i / 16])
        writer.book.close()
    _assert_packages_equal(*paths)
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize('allowed', [True, False])
def test_zip64_retains_stock_semantics(tmp_path, monkeypatch, allowed):
    monkeypatch.setattr(zipfile, 'ZIP64_LIMIT', 1024)
    monkeypatch.setattr(packaging, '_MIN_MEMBER_BYTES', 1)
    paths = [tmp_path / kind / 'output.xlsx' for kind in ('stock', 'backend')]
    for path, stock in zip(paths, (True, False), strict=True):
        path.parent.mkdir()
        writer = _writer(path, stock=stock, options={'tmpdir': str(path.parent), 'use_zip64': allowed})
        writer.book.set_properties({'created': datetime(2020, 1, 2)})
        sheet = writer.book.add_worksheet()
        for i in range(200):
            sheet.write_row(i, 0, [i, i / 16])
        if allowed:
            writer.book.close()
        else:
            with pytest.raises(xlsxwriter.exceptions.FileSizeError):
                writer.book.close()
    if allowed:
        _assert_packages_equal(*paths)
    assert list(paths[1].parent.iterdir()) == [paths[1]]


def test_deflate_streaming_uses_stock_level_and_bounded_reads(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 8192
    source, destination = tmp_path / 'source', tmp_path / 'deflated'
    source.write_bytes(payload)
    calls = []
    original = zlib.compressobj
    source_open = open
    reads = []

    class Reader:
        def __enter__(self):
            self.handle = source_open(source, 'rb')
            return self

        def __exit__(self, *args):
            self.handle.close()

        def read(self, size):
            reads.append(size)
            assert 0 < size <= packaging._CHUNK_BYTES
            return self.handle.read(size)

    def compressor(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(packaging.zlib, 'compressobj', compressor)
    monkeypatch.setattr(packaging, 'open', lambda *args: Reader(), raising=False)
    member = packaging._deflate(str(source), destination)
    assert calls == [(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)]
    assert member.size == len(payload)
    assert member.crc == zlib.crc32(payload)
    assert destination.read_bytes() == zlib.compress(payload, level=6, wbits=-15)
    assert member.compressed_size == destination.stat().st_size
    assert len(reads) > 1


def test_pending_submission_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, '_MIN_MEMBER_BYTES', 1)
    observations = {'pending': 0, 'maximum': 0, 'submitted': 0}

    class Result:
        def __init__(self, value):
            self.value = value

        def result(self):
            observations['pending'] -= 1
            return self.value

    class Executor:
        def __init__(self, max_workers, **kwargs):
            assert 1 <= max_workers <= packaging._MAX_WORKERS

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, *args):
            observations['submitted'] += 1
            observations['pending'] += 1
            observations['maximum'] = max(observations['maximum'], observations['pending'])
            return Result(function(*args))

    monkeypatch.setattr(packaging, 'ThreadPoolExecutor', Executor)
    writer = _writer(tmp_path / 'bounded.xlsx', stock=False)
    _populate(writer, 'main')
    ExcelExportBackend().close_writer(writer)
    assert observations['submitted'] > packaging._MAX_WORKERS
    assert observations['maximum'] <= packaging._MAX_WORKERS
    assert observations['pending'] == 0


def test_concurrent_workbooks_keep_hooks_and_package_state_isolated(tmp_path, monkeypatch):
    states = []

    class State(packaging._PackageState):
        def __init__(self, workbook):
            super().__init__(workbook)
            states.append(weakref.ref(self))

    monkeypatch.setattr(packaging, '_PackageState', State)
    original_zipfile = xlsxwriter.workbook.ZipFile
    paths = [tmp_path / f'{i}.xlsx' for i in range(3)]
    writers = [_writer(path, stock=i == 0) for i, path in enumerate(paths)]
    for writer in writers:
        _populate(writer, 'csv')
    ExcelExportBackend().close_writer(writers[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(ExcelExportBackend().close_writer, writers[1:]))
    assert xlsxwriter.workbook.ZipFile is original_zipfile is zipfile.ZipFile
    assert len(states) == 2
    assert all(state() is None for state in states)
    assert all('_store_workbook' not in writer.book.__dict__ for writer in writers)
    for path in paths[1:]:
        _assert_packages_equal(paths[0], path)


def test_exception_chain_cleanup_is_owned_direct_and_cycle_safe(tmp_path):
    backend = ExcelExportBackend()
    a, b = [backend.create_writer(str(tmp_path / f'{name}.xlsx')) for name in ('a', 'b')]

    def xml(path):
        writer = packaging.XMLwriter()
        writer._set_xml_writer(str(path))
        return writer

    owned = xml(Path(a.temporary_directory.name) / 'owned.xml')
    foreign = xml(Path(b.temporary_directory.name) / 'foreign.xml')
    external = xml(tmp_path / 'external.xml')
    hidden_box = [xml(Path(a.temporary_directory.name) / 'hidden.xml')]
    stream = io.StringIO()
    direct_file = open(Path(a.temporary_directory.name) / 'binary', 'wb')
    archive_a, archive_b = [zipfile.ZipFile(writer.path, 'w') for writer in (a, b)]

    def cause(owned_writer, foreign_writer, external_writer, caller_stream,
              container, zip_a, zip_b, os_file):
        raise RuntimeError('underlying fault')

    try:
        try:
            cause(owned, foreign, external, stream, hidden_box, archive_a, archive_b, direct_file)
        except RuntimeError as inner:
            try:
                raise ValueError('outer fault') from inner
            except ValueError as outer:
                inner.__context__ = outer
                before = outer.__traceback__
                packaging.cleanup_failed_workbook(a.book, outer)
                assert outer.__traceback__ is before
        assert owned.fh.closed and direct_file.closed
        assert archive_a.fp is not None  # A matching path alone does not prove archive ownership.
        assert not foreign.fh.closed and not external.fh.closed
        assert not stream.closed and archive_b.fp is not None
        assert not hidden_box[0].fh.closed  # No recursive container walk.
    finally:
        for handle in (owned.fh, foreign.fh, external.fh, hidden_box[0].fh, stream, direct_file, archive_a, archive_b):
            handle.close()
        backend.discard_writer(a)
        backend.discard_writer(b)


def test_traceback_cleanup_skips_file_like_workbook_target(tmp_path):
    backend = ExcelExportBackend()
    writer = backend.create_writer(str(tmp_path / 'unused.xlsx'))
    caller_stream = io.BytesIO()
    writer.book.filename = caller_stream
    owned = packaging.XMLwriter()
    owned._set_xml_writer(str(Path(writer.temporary_directory.name) / 'owned.xml'))
    try:
        try:
            raise RuntimeError('caller-owned stream')
        except RuntimeError as error:
            packaging.cleanup_failed_workbook(writer.book, error)
        assert not caller_stream.closed and not owned.fh.closed
    finally:
        owned.fh.close()
        caller_stream.close()
        backend.discard_writer(writer)


def test_file_like_workbook_uses_stock_close_without_closing_caller_stream():
    stream = io.BytesIO()
    book = xlsxwriter.Workbook(stream)
    assert not packaging.enable_parallel_package(book)
    assert '_store_workbook' not in book.__dict__
    book.add_worksheet().write(0, 0, 'Synthetic')
    book.close()
    assert not stream.closed
    with zipfile.ZipFile(stream) as archive:
        assert archive.testzip() is None

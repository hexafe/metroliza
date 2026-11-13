"""Bounded, instance-local packaging for the validated XlsxWriter interface.

Workbook preparation stays upstream. Only large on-disk members are deflated
in parallel; disk spools keep memory independent of worksheet/package size.
Unknown interfaces and precompression failures retain upstream member writing.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import io
from itertools import islice
import os
from pathlib import Path
import shutil
import tempfile
from types import FrameType, FunctionType, MethodType
from typing import Any, Callable, Iterator
import zipfile
import zlib

import xlsxwriter
from xlsxwriter.workbook import Workbook
from xlsxwriter.theme import Theme
from xlsxwriter.xmlwriter import XMLwriter


_MIN_MEMBER_BYTES = 256 * 1024
_CHUNK_BYTES = 256 * 1024
_MAX_WORKERS = 4
# Python 3.11 / XlsxWriter 3.2.9: bytecode, names and constants, no source paths.
_STORE_DIGEST = '0b7602c46edc653f5f5563dfd7767086fa9c1bb770fdb58fb28e40c83d0066b7'
_ZIP_DIGESTS = (
    'ca6ad2805fd9ef415ae6b6f8d764c150d38de90b146d1186cf69e1741272b00d',
    'c92f4eb43638dc91a04d9b4b4cf61984b2d15cd0af6a7f42b35fef4048287467',
)


@dataclass(frozen=True)
class _DeflatedMember:
    path: Path
    size: int
    crc: int
    compressed_size: int


def _deflate(source: str, destination: Path) -> _DeflatedMember:
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    crc = size = 0
    with open(source, 'rb') as src, destination.open('wb') as dst:
        while data := src.read(_CHUNK_BYTES):
            size += len(data)
            crc = zlib.crc32(data, crc)
            dst.write(compressor.compress(data))
        dst.write(compressor.flush())
        compressed_size = dst.tell()
    return _DeflatedMember(destination, size, crc, compressed_size)


class _FinishedCompressor:
    """Let the stdlib write handle finalise headers without deflating twice."""

    def flush(self) -> bytes:
        return b''


class _PreparedZipFile(zipfile.ZipFile):
    def __init__(self, state: _PackageState, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._package_state = state
        state.archive = self

    def write(
        self, filename: Any, arcname: Any = None,
        compress_type: Any = None, compresslevel: Any = None,
    ) -> None:
        member = self._package_state.members.get(filename)
        if member is None:
            return super().write(filename, arcname, compress_type, compresslevel)
        info = zipfile.ZipInfo.from_file(filename, arcname, strict_timestamps=getattr(self, '_strict_timestamps'))
        info.compress_type = self.compression
        setattr(info, '_compresslevel', self.compresslevel)
        # open() retains stock ZIP64 selection, attributes, header layout and
        # central-directory accounting. Only the already-deflated payload differs.
        with self.open(info, 'w') as raw_handle:
            handle: Any = raw_handle
            handle._compressor = _FinishedCompressor()
            with member.path.open('rb') as source:
                shutil.copyfileobj(source, handle._fileobj, _CHUNK_BYTES)
            handle._file_size = member.size
            handle._compress_size = member.compressed_size
            handle._crc = member.crc
        member.path.unlink()


class _PackageState:
    def __init__(self, workbook: Any) -> None:
        self.workbook = workbook
        self.members: dict[str, _DeflatedMember] = {}
        self.packager: Any = None
        self.archive: _PreparedZipFile | None = None
        self.spools: tempfile.TemporaryDirectory[str] | None = None

    def prepare(self, files: list[tuple[str, str, bool]]) -> None:
        """Submit at most one bounded batch; retain no XML payload in memory."""
        try:
            candidates = iter(item[0] for item in files
                              if os.path.getsize(item[0]) >= _MIN_MEMBER_BYTES)
            first = list(islice(candidates, _MAX_WORKERS))
            if not first:
                return
            self.spools = tempfile.TemporaryDirectory(dir=self.workbook.tmpdir)
            workers = min(_MAX_WORKERS, os.cpu_count() or 1)
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='xlsx-deflate') as pool:
                batch = first
                index = 0
                while batch:
                    pending = []
                    for source in batch:
                        destination = Path(self.spools.name) / str(index)
                        index += 1
                        pending.append((source, pool.submit(_deflate, source, destination)))
                    for source, future in pending:
                        self.members[source] = future.result()
                    batch = list(islice(candidates, _MAX_WORKERS))
        except Exception as error:
            # Preparation happened exactly once. Keep its original files and let
            # the same upstream store loop use stock ZipFile.write for all members.
            self.members.clear()
            if self.spools is not None:
                _cleanup_step(self.spools.cleanup, error)

    def get_packager(self, original: Callable[[], Any]) -> Any:
        packager = original()
        self.packager = packager
        create_package = packager._create_package

        def create_prepared_package() -> Any:
            files = create_package()
            self.prepare(files)
            return files

        packager._create_package = create_prepared_package
        return packager

    def cleanup(self, error: BaseException | None) -> None:
        if self.archive is not None:
            _cleanup_step(self.archive.close, error)
        discard_workbook(self.workbook, error)
        if self.spools is not None:
            _cleanup_step(self.spools.cleanup, error)
        if self.packager is not None:
            for filename, _, _ in self.packager.filenames:
                if isinstance(filename, str):
                    _cleanup_step(lambda: Path(filename).unlink(missing_ok=True), error)


def _cleanup_step(action: Callable[[], Any], error: BaseException | None) -> None:
    try:
        action()
    except BaseException as secondary:
        if error is None:
            raise
        try:
            error.add_note(f'Workbook cleanup also failed: {type(secondary).__name__}: {secondary}')
        except BaseException:
            pass


def _real_path(value: Any) -> str | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    return os.path.normcase(os.path.realpath(os.fsdecode(value)))


def _inside_scratch(handle: Any, scratch: str) -> bool:
    if not isinstance(handle, io.IOBase) or isinstance(handle, (io.StringIO, io.BytesIO)):
        return False
    if handle.closed:
        return False
    path = _real_path(getattr(handle, 'name', None))
    return path is not None and os.path.commonpath((path, scratch)) == scratch


def cleanup_failed_workbook(workbook: Any, error: BaseException) -> None:
    """Close owned 3.2.9 serializer/ZIP handles retained by an exception.

    Inspect direct locals only; never clear or alter the original traceback.
    The private scratch marker is assigned by the backend to this exact book.
    """
    _cleanup_step(lambda: _cleanup_traceback(workbook, error), error)


def _cleanup_traceback(workbook: Any, error: BaseException) -> None:
    if not isinstance(workbook, Workbook) or xlsxwriter.__version__ != '3.2.9':
        return
    scratch = _real_path(getattr(workbook, '_metroliza_package_scratch', None))
    target = _real_path(workbook.filename)
    if scratch is None or target is None or _real_path(workbook.tmpdir) != scratch:
        return
    seen_handles: set[int] = set()
    for frame in _exception_frames(error):
        scope = frame.f_locals
        if frame.f_code.co_name == '_store_workbook' and scope.get('self') is workbook:
            _cleanup_step(lambda: _close_owned_archive(scope.get('xlsx_file'), target, seen_handles), error)
        for value in tuple(scope.values()):
            _cleanup_step(lambda: _close_trace_local(value, scratch, seen_handles), error)


def _exception_locals(error: BaseException) -> Iterator[Any]:
    for frame in _exception_frames(error):
        yield from tuple(frame.f_locals.values())


def _exception_frames(error: BaseException) -> Iterator[FrameType]:
    pending = [error]
    seen_errors: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen_errors:
            continue
        seen_errors.add(id(current))
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
        cursor = current.__traceback__
        while cursor is not None:
            yield cursor.tb_frame
            cursor = cursor.tb_next


def _close_owned_archive(value: Any, target: str, seen: set[int]) -> None:
    if not isinstance(value, zipfile.ZipFile) or id(value) in seen or value.fp is None:
        return
    if value.mode == 'w' and _real_path(value.filename) == target and _real_path(value.fp.name) == target:
        seen.add(id(value))
        value.close()


def _close_trace_local(value: Any, scratch: str, seen: set[int]) -> None:
    # Theme duplicates XMLwriter's interface but does not inherit XMLwriter.
    if isinstance(value, (XMLwriter, Theme)) and value.internal_fh is True:
        value = value.fh
    if id(value) in seen:
        return
    # Packager image/VBA writes use direct os_file locals, not XMLwriter.
    if _inside_scratch(value, scratch):
        seen.add(id(value))
        value.close()


def _code_digest(method: Any) -> str:
    code = method.__code__
    return hashlib.sha256(code.co_code + repr((code.co_names, code.co_consts)).encode()).hexdigest()


def _supported(workbook: Any) -> bool:
    if xlsxwriter.__version__ != '3.2.9' or type(workbook) is not Workbook:
        return False
    if (workbook.in_memory or '_store_workbook' in workbook.__dict__
            or not isinstance(workbook.filename, (str, os.PathLike))):
        return False
    method = Workbook._store_workbook
    zip_methods = (getattr(zipfile.ZipFile, '_open_to_write'), getattr(zipfile, '_ZipWriteFile').close)
    return (_code_digest(method) == _STORE_DIGEST
            and method.__globals__.get('ZipFile') is zipfile.ZipFile
            and tuple(map(_code_digest, zip_methods)) == _ZIP_DIGESTS)


def _store_parallel_workbook(book: Any, original: Any) -> None:
    try:
        state = _PackageState(book)
    except Exception:
        book.__dict__.pop('_store_workbook', None)
        original(book)
        return
    get_packager = book._get_packager
    previous = book.__dict__.get('_get_packager')
    try:
        book._get_packager = lambda: state.get_packager(get_packager)
        globals_copy = dict(original.__globals__)
        globals_copy['ZipFile'] = lambda *args, **kwargs: _PreparedZipFile(state, *args, **kwargs)
        upstream = FunctionType(original.__code__, globals_copy)
    except Exception:
        book.__dict__.pop('_store_workbook', None)
        if previous is None:
            book.__dict__.pop('_get_packager', None)
        else:
            book._get_packager = previous
        original(book)
        return
    error: BaseException | None = None
    try:
        upstream(book)
    except BaseException as caught:
        error = caught
        cleanup_failed_workbook(book, caught)
        raise
    finally:
        book.__dict__.pop('_store_workbook', None)
        if previous is None:
            book.__dict__.pop('_get_packager', None)
        else:
            book._get_packager = previous
        try:
            state.cleanup(error)
        finally:
            # Break temporary closures without relying on cyclic collection.
            if state.packager is not None:
                state.packager.__dict__.pop('_create_package', None)
            state.packager = None
            state.archive = None


def enable_parallel_package(workbook: Any) -> bool:
    """Install a close hook on this workbook only, or leave stock close intact."""
    try:
        supported = _supported(workbook)
    except Exception:
        supported = False
    if not supported:
        return False
    original = Workbook._store_workbook

    def store(book: Any) -> None:
        _store_parallel_workbook(book, original)

    try:
        workbook._store_workbook = MethodType(store, workbook)
    except Exception:
        return False
    return True


def discard_workbook(workbook: Any, error: BaseException | None = None) -> None:
    """Release workbook-owned scratch files without serialising a package."""
    if not isinstance(workbook, Workbook):
        return
    workbook.__dict__.pop('_store_workbook', None)
    for sheet in workbook.worksheets():
        handle = getattr(sheet, 'row_data_fh', None)
        if handle is not None and not handle.closed:
            _cleanup_step(handle.close, error)
            sheet.row_data_fh_closed = True
        filename = getattr(sheet, 'row_data_filename', None)
        if filename:
            _cleanup_step(lambda: Path(filename).unlink(missing_ok=True), error)
        if getattr(sheet, 'internal_fh', False):
            _cleanup_step(sheet.fh.close, error)
    workbook.fileclosed = True

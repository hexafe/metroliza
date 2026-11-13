"""Database-free metadata reading for the pre-import review step (#1100).

``MetadataReviewReader`` re-opens the reviewed READY reports of a
``ParsePreflightResult`` and reads their metadata with the existing parser
metadata extraction: ``light`` (filename and embedded header text, the fast
mode) or ``complete`` (adds header OCR).  It never opens the destination
database for writing and constructs parsers without a connection.

Each file is checked against the content fingerprint recorded at review time,
so a changed source is reported as such and never silently re-approved.  The
class is Qt-free; the UI layer's metadata review worker runs it off the GUI
thread.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from metroliza.parsing import report_parser_factory
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.header_ocr_backend import (
    DEFAULT_HEADER_OCR_BACKEND,
    default_rapidocr_latin_model_paths,
    missing_rapidocr_latin_model_paths,
)
from metroliza.parsing.parser_plugin_contracts import infer_source_format
from metroliza.parsing.preflight import (
    ParseFilePreflight,
    ParsePreflightResult,
    is_supported_report_archive,
    safe_unpack_report_archive,
)
from metroliza.parsing.source_inspection import (
    SourceChangedAfterInspectionError,
    SourceInspectionContext,
)
from metroliza.reports.report_metadata_models import MetadataSelectionResult
from metroliza.reports.report_metadata_review import (
    ROW_CHANGED,
    ROW_FAILED,
    ROW_UNSUPPORTED,
)

MODE_FAST = "light"
MODE_OCR = "complete"
READING_OK = "ok"

NOTE_SOURCE_CHANGED = "Changed since review. Review reports again before importing."
NOTE_UNSUPPORTED = "This parser's metadata is imported as detected and cannot be edited here."
NOTE_FAILED = "Metadata could not be read from this report."
NOTE_ARCHIVE_FAILED = "The source archive could not be opened."


@dataclass(frozen=True)
class MetadataReading:
    """Outcome of reading one report. Notes are coarse and never carry exception text."""

    occurrence_id: str
    status: str
    mode: str
    selection: MetadataSelectionResult | None = None
    note: str = ""
    ocr_note: str = ""


@dataclass(frozen=True)
class MetadataReadSummary:
    total: int
    read: int
    failed: int
    cancelled: int


def _safe_ocr_note(metadata_json: dict | None) -> str:
    """Reduce OCR diagnostics to a fixed vocabulary (raw errors may embed paths)."""

    diagnostics = metadata_json or {}
    error = str(diagnostics.get("header_ocr_error") or "")
    if error:
        if error == "header_ocr_disabled":
            return "OCR is disabled."
        if error.startswith("header_ocr_models_missing"):
            return "OCR models are not installed."
        if error.startswith("unsupported_header_ocr_backend"):
            return "The configured OCR backend is not supported."
        if error in {"header_ocr_no_records", "header_ocr_no_header_items"}:
            return "OCR found no header text."
        return "OCR is unavailable or failed."
    if diagnostics.get("header_extraction_mode") == "ocr":
        return "Header read with OCR."
    return "Header text was already readable; OCR was not needed."


def ocr_unavailable_reason() -> str:
    """Why header OCR cannot run here, or ``""`` when it looks usable.

    Mirrors the checks the OCR extraction makes before it imports the engine
    (backend setting and model files).  The engine import itself is not probed:
    packaged builds run it in a private worker process, so a missing module is
    reported after a run through the coarse OCR note instead.
    """

    backend = os.environ.get("METROLIZA_HEADER_OCR_BACKEND", DEFAULT_HEADER_OCR_BACKEND).strip().lower()
    if backend in {"", "none", "off", "disabled"}:
        return "OCR is disabled in this installation."
    if backend != DEFAULT_HEADER_OCR_BACKEND:
        return "The configured OCR backend is not supported."
    model_paths = default_rapidocr_latin_model_paths(os.environ.get("METROLIZA_HEADER_OCR_MODEL_DIR") or None)
    if missing_rapidocr_latin_model_paths(model_paths):
        return "OCR is unavailable: the OCR models are not installed."
    return ""


class MetadataReviewReader:
    """Read metadata for reviewed READY reports without any database write."""

    def __init__(
        self,
        preflight: ParsePreflightResult,
        *,
        parser_factory: Callable | None = None,
    ) -> None:
        if preflight.cancelled:
            raise ValueError("A cancelled preflight result cannot be used for metadata review.")
        self._preflight = preflight
        self._parser_factory = parser_factory or report_parser_factory.get_parser
        self._items = {item.stable_occurrence_id: item for item in preflight.files}

    @property
    def preflight(self) -> ParsePreflightResult:
        return self._preflight

    def item(self, occurrence_id: str) -> ParseFilePreflight | None:
        return self._items.get(occurrence_id)

    def read(
        self,
        occurrence_ids: Iterable[str],
        *,
        mode: str = MODE_FAST,
        should_cancel: Callable[[], bool] = lambda: False,
        on_reading: Callable[[MetadataReading], None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        workers: int | None = None,
    ) -> MetadataReadSummary:
        """Read each occurrence in order; cancellation is checked between reports.

        ``workers`` is the review-pool size for the quick read; ``None`` lets the compute
        budget decide and 0 or 1 reads in-process.  OCR reads always run in-process.
        Readings and their order are identical either way.
        """

        if mode not in (MODE_FAST, MODE_OCR):
            raise ValueError(f"Unsupported metadata review mode: {mode}")
        ordered = [occ for occ in dict.fromkeys(occurrence_ids) if occ in self._items]
        counts = {"read": 0, "failed": 0, "processed": 0}

        def emit(reading: MetadataReading) -> None:
            counts["processed"] += 1
            counts["read" if reading.status == READING_OK else "failed"] += 1
            if on_reading is not None:
                on_reading(reading)
            if on_progress is not None:
                on_progress(
                    counts["processed"], len(ordered), self._items[reading.occurrence_id].display_name
                )

        if ordered:
            self._read_batch(ordered, mode, should_cancel, emit, workers=workers)
        return MetadataReadSummary(
            len(ordered), counts["read"], counts["failed"], len(ordered) - counts["processed"]
        )

    def _read_batch(self, ordered, mode, should_cancel, emit, *, workers=None) -> None:
        with ExitStack() as stack:
            try:
                paths = stack.enter_context(self._resolved_paths(ordered))
            except (OSError, ValueError):  # unreadable or unsafe archive (ReadError is an OSError)
                for occurrence_id in ordered:
                    emit(MetadataReading(occurrence_id, ROW_FAILED, mode, note=NOTE_ARCHIVE_FAILED))
                return
            readings = stack.enter_context(
                closing(self._readings_in_order(ordered, paths, mode, should_cancel, workers))
            )
            for _occurrence_id, read_next in readings:
                if should_cancel():
                    break
                reading = read_next()
                if reading is None:  # the pool stopped on cancellation
                    break
                emit(reading)

    def _pool_size(self, count: int, mode: str, workers: int | None) -> int:
        if (
            mode != MODE_FAST
            or self._parser_factory is not _IN_PROCESS_PARSER_FACTORY
            or getattr(self._read_one, "__func__", None) is not _IN_PROCESS_READ_ONE
        ):
            return 0
        from metroliza.parsing import review_pool

        if workers is None:
            return review_pool.resolve_review_worker_count(count)
        return max(0, int(workers))

    def _readings_in_order(self, ordered, paths, mode, should_cancel, workers):
        """Yield ``(occurrence_id, read_next)`` in order; ``read_next()`` reads (or takes) one.

        The quick read of a large batch runs ``read_metadata_one`` in the review pool
        (``review_pool``); the caller still checks cancellation before each report.
        """

        count = self._pool_size(len(ordered), mode, workers)
        if count < 2:
            for occurrence_id in ordered:
                yield occurrence_id, partial(
                    self._read_one, self._items[occurrence_id], paths.get(occurrence_id), mode
                )
            return
        from metroliza.parsing import review_pool

        pooled = review_pool.read_metadata_in_order(
            [(self._items[occ], paths.get(occ)) for occ in ordered],
            mode=mode,
            database_path=self._preflight.database_path,
            workers=count,
            should_cancel=should_cancel,
            read_serial=lambda item, path: self._read_one(item, path, mode),
        )
        with closing(pooled):
            for occurrence_id in ordered:
                yield occurrence_id, partial(next, pooled, None)
            next(pooled, None)  # let a complete run shut its workers down gracefully

    # -- internals ---------------------------------------------------------

    @contextmanager
    def _resolved_paths(self, occurrence_ids: list[str]):
        source = Path(self._preflight.source_path)
        if source.is_file() and is_supported_report_archive(source):
            # The review scan extracted into a temporary directory that is gone.
            with TemporaryDirectory() as extracted:
                safe_unpack_report_archive(source, extracted)
                yield {
                    occ: Path(extracted).joinpath(*PurePosixPath(occ).parts)
                    for occ in occurrence_ids
                }
        elif source.is_file():
            yield {occ: source for occ in occurrence_ids}
        else:
            yield {occ: source.joinpath(*PurePosixPath(occ).parts) for occ in occurrence_ids}

    def _read_one(
        self, item: ParseFilePreflight, path: Path | None, mode: str
    ) -> MetadataReading:
        return read_metadata_one(
            item,
            path,
            mode,
            database_path=self._preflight.database_path,
            parser_factory=self._parser_factory,
        )


def _metadata_instance_keys(parser):
    attributes = object.__getattribute__(parser, "__dict__")
    if type(attributes) is not dict:
        return None
    try:
        keys = tuple(attributes)
    except RuntimeError:  # native dictionary changed during the key-only snapshot
        return None
    return keys if all(type(key) is str for key in keys) else None


def _metadata_open_supported(parser, parser_factory):
    # Plugins, subclasses and customized CMM instances keep their public full-open path.
    if type(parser) is not CMMReportParser:
        return False
    keys = _metadata_instance_keys(parser)
    if keys is None:
        return False
    return (
        (parser_factory is None or parser_factory is _IN_PROCESS_PARSER_FACTORY)
        and CMMReportParser.open_report is _CMM_FULL_OPEN
        and CMMReportParser.extract_metadata is _CMM_EXTRACT_METADATA
        and CMMReportParser._cached_embedded_lines_for_open_report is _CMM_CACHED_LINES
        and "open_report" not in keys
        and "extract_metadata" not in keys
        and "_cached_embedded_lines_for_open_report" not in keys
    )


def read_metadata_one(
    item: ParseFilePreflight,
    path: Path | None,
    mode: str,
    *,
    database_path: str,
    parser_factory: Callable | None = None,
) -> MetadataReading:
    """Read one reviewed report's metadata (the review pool's workers run this as well)."""

    occurrence_id = item.stable_occurrence_id
    if path is None or not path.is_file() or not item.fingerprint or not item.parser_id:
        return MetadataReading(occurrence_id, ROW_CHANGED, mode, note=NOTE_SOURCE_CHANGED)
    try:
        inspection = SourceInspectionContext.from_path(
            path, source_format=infer_source_format(path)
        )
        sha256_value = inspection.sha256
        if not sha256_value or f"sha256:{sha256_value}" != item.fingerprint:
            return MetadataReading(occurrence_id, ROW_CHANGED, mode, note=NOTE_SOURCE_CHANGED)
        parser = report_parser_factory.invoke_parser_factory(
            parser_factory or report_parser_factory.get_parser,
            str(path),
            database_path,
            source_inspection=inspection,
            expected_plugin_id=item.parser_id,
            expected_registry_generation_id=item.registry_generation_id,
            metadata_parsing_mode=mode,
        )
        if not getattr(parser, "supports_metadata_review_override", False):
            return MetadataReading(occurrence_id, ROW_UNSUPPORTED, mode, note=NOTE_UNSUPPORTED)
        if hasattr(parser, "metadata_parsing_mode"):
            parser.metadata_parsing_mode = mode
        if _metadata_open_supported(parser, parser_factory):
            CMMReportParser.open_metadata_report(parser)
        else:
            parser.open_report()
        selection = parser.extract_metadata()
        inspection.verified_sha256()
    except (
        SourceChangedAfterInspectionError,
        report_parser_factory.ParserApprovalMismatchError,
        report_parser_factory.ParserAmbiguityError,
        report_parser_factory.UnsupportedReportFormatError,
    ):
        return MetadataReading(occurrence_id, ROW_CHANGED, mode, note=NOTE_SOURCE_CHANGED)
    except Exception:  # noqa: BLE001 - one unreadable report must not stop the batch
        return MetadataReading(occurrence_id, ROW_FAILED, mode, note=NOTE_FAILED)
    if not isinstance(selection, MetadataSelectionResult):
        return MetadataReading(occurrence_id, ROW_FAILED, mode, note=NOTE_FAILED)
    return MetadataReading(
        occurrence_id,
        READING_OK,
        mode,
        selection=selection,
        ocr_note=_safe_ocr_note(selection.metadata.metadata_json) if mode == MODE_OCR else "",
    )


# The reader the review pool reproduces in its workers; anything else stays in-process.
_IN_PROCESS_PARSER_FACTORY = report_parser_factory.get_parser
_IN_PROCESS_READ_ONE = MetadataReviewReader._read_one
_CMM_FULL_OPEN = CMMReportParser.open_report
_CMM_EXTRACT_METADATA = CMMReportParser.extract_metadata
_CMM_CACHED_LINES = CMMReportParser._cached_embedded_lines_for_open_report


__all__ = [
    "MODE_FAST",
    "MODE_OCR",
    "READING_OK",
    "MetadataReadSummary",
    "MetadataReading",
    "MetadataReviewReader",
    "ocr_unavailable_reason",
    "read_metadata_one",
]

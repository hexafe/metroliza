import inspect
import logging
import re
import time

from modules.cmm_report_parser import CMMReportParser
import modules.custom_logger as custom_logger
from PyQt6.QtCore import QThread, pyqtSignal
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from modules.report_fingerprint import build_parser_fingerprint
from modules.contracts import ParseRequest, validate_parse_request
from modules.characteristic_alias_service import ensure_characteristic_alias_schema
from modules.db import execute_with_retry, sqlite_connection_scope
from modules.log_context import build_parse_log_extra, get_operation_logger
from modules.progress_status import build_three_line_status


@dataclass(frozen=True)
class ParseBatchResult:
    parsed_files: int
    total_files: int


PARSE_TELEMETRY_BATCH_SIZE = 25


def build_report_fingerprints_from_rows(rows, should_cancel=lambda: False):
    report_fingerprints = set()
    add_fingerprint = report_fingerprints.add

    for row in rows:
        if should_cancel():
            break

        report_id, reference, fileloc, filename, date_value, sample_number = row
        if report_id is not None:
            add_fingerprint(f"id:{report_id}")
            continue

        add_fingerprint(
            "|".join(
                str(part)
                for part in (
                    reference or '',
                    fileloc or '',
                    filename or '',
                    date_value or '',
                    sample_number or '',
                )
            )
        )
    return report_fingerprints


def parse_new_reports(
    report_paths,
    report_fingerprints,
    parser_factory,
    persist_report,
    should_cancel=lambda: False,
    on_progress=None,
    on_file_parsed=None,
):
    parsed_files = 0
    total_files = len(report_paths)

    for report in report_paths:
        if should_cancel():
            break

        report_parse_start = time.perf_counter()
        parser = parser_factory(report)
        fingerprint = build_parser_fingerprint(parser)
        if fingerprint not in report_fingerprints:
            persist_report(parser)
            report_fingerprints.add(fingerprint)
        parsed_files += 1
        parse_duration_s = time.perf_counter() - report_parse_start

        if on_file_parsed:
            on_file_parsed(parser, parsed_files, total_files, parse_duration_s)

        if on_progress:
            on_progress(parsed_files, total_files)

    return ParseBatchResult(parsed_files=parsed_files, total_files=total_files)


logger = get_operation_logger(logging.getLogger(__name__), "parse_reports")


class ParseReportsThread(QThread):
    LOOKUP_BATCH_SIZE = 250
    PROGRESS_STAGE_RANGES = {
        'discover_reports': (0, 15),
        'load_existing_reports': (15, 30),
        'parse_reports': (30, 100),
    }

    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    parsing_finished = pyqtSignal()

    def __init__(self, parse_request: ParseRequest):
        super().__init__()

        validated_request = validate_parse_request(parse_request)

        # Initialize the thread with validated request values
        self.directory = validated_request.source_directory
        self.db_file = validated_request.db_file
        self.parsing_canceled = False
        self._extracted_archive_dir = None
        self._last_emitted_progress = -1
        self._report_lookup_candidates = {
            'filenames': set(),
            'reference_dates': set(),
        }

    @staticmethod
    def _build_filename_lookup_candidates(report_paths):
        filenames = set()
        reference_dates = set()
        date_pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}"
        reference_pattern = r"([A-Z][A-Za-z0-9]{4}\d{1,5}(_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5})"

        for report_path in report_paths:
            filename = Path(report_path).name
            filenames.add(filename)

            date_match = re.findall(date_pattern, filename)
            date_value = date_match[-1] if date_match else None
            if date_value is not None:
                date_value = date_value.replace('.', '-').replace('_', '-').replace('/', '-')

            reference_match = re.match(reference_pattern, filename)
            reference_value = reference_match.group(0) if reference_match else None

            if reference_value and date_value:
                reference_dates.add((reference_value, date_value))

        return {
            'filenames': filenames,
            'reference_dates': reference_dates,
        }

    @staticmethod
    def _batched_values(values, batch_size):
        values_list = list(values)
        for idx in range(0, len(values_list), batch_size):
            yield values_list[idx:idx + batch_size]

    @staticmethod
    def _clamp_progress(value):
        return max(0, min(100, int(round(value))))

    def _emit_progress(self, value):
        clamped_value = self._clamp_progress(value)
        progress_value = max(clamped_value, self._last_emitted_progress)
        if progress_value == self._last_emitted_progress:
            return

        self._last_emitted_progress = progress_value
        self.update_progress.emit(progress_value)

    def _emit_stage_progress(self, stage_name, fraction=1.0):
        start, end = self.PROGRESS_STAGE_RANGES[stage_name]
        safe_fraction = max(0.0, min(1.0, float(fraction)))
        self._emit_progress(start + ((end - start) * safe_fraction))

    @staticmethod
    def _format_elapsed_or_eta(seconds):
        safe_seconds = max(0, int(seconds))
        minutes, remaining_seconds = divmod(safe_seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{remaining_minutes:02d}:{remaining_seconds:02d}"
        return f"{remaining_minutes:d}:{remaining_seconds:02d}"

    def _build_parse_label(self, *, parsed_files, total_files, start_time):
        stage_line = "Parsing reports..."
        if total_files <= 0:
            return build_three_line_status(stage_line, "Files remaining 0", "ETA --")

        remaining_files = max(0, total_files - parsed_files)
        detail_line = f"File {parsed_files}/{total_files}, remaining {remaining_files}"

        elapsed_seconds = max(0.0, time.perf_counter() - start_time)
        if parsed_files < 2 or elapsed_seconds < 1.0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        files_per_second = parsed_files / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if files_per_second <= 0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        eta_seconds = remaining_files / files_per_second
        elapsed_display = self._format_elapsed_or_eta(elapsed_seconds)
        eta_display = self._format_elapsed_or_eta(eta_seconds)
        return build_three_line_status(stage_line, detail_line, f"{elapsed_display} elapsed, ETA {eta_display}")

    @staticmethod
    def _build_archive_extension_set():
        archive_extensions = set()
        for _format_name, extensions, _description in shutil.get_unpack_formats():
            archive_extensions.update(ext.lower() for ext in extensions)
        return archive_extensions

    def _resolve_report_root(self):
        source_path = Path(self.directory)

        if source_path.is_file() and source_path.suffix.lower() in self._build_archive_extension_set():
            self._extracted_archive_dir = TemporaryDirectory()
            shutil.unpack_archive(str(source_path), self._extracted_archive_dir.name)
            return Path(self._extracted_archive_dir.name)

        return source_path

    def get_list_of_reports(self):
        try:
            pdf_files = []
            report_root = self._resolve_report_root()
            logger.info(
                "Parse discovery started",
                extra=build_parse_log_extra(
                    source_path=report_root,
                    parsed_count=0,
                    cancel_flag=self.parsing_canceled,
                ),
            )
            self.update_label.emit(
                build_three_line_status(
                    "Parsing reports...",
                    "Discovering report files in source directory",
                    "ETA --",
                )
            )
            self._emit_stage_progress('discover_reports', 0.0)
            for path in report_root.glob("**/*.[Pp][Dd][Ff]"):
                if self.parsing_canceled:
                    break
                if path.is_file() and path.stat().st_size:
                    pdf_files.append(path)

            self._report_lookup_candidates = self._build_filename_lookup_candidates(pdf_files)
            self._emit_stage_progress('discover_reports', 1.0)
            logger.info(
                "Parse discovery finished",
                extra=build_parse_log_extra(
                    source_path=report_root,
                    total_files=len(pdf_files),
                    parsed_count=0,
                    cancel_flag=self.parsing_canceled,
                ),
            )
            return pdf_files
        except Exception as e:
            self.log_and_exit(e)

    def get_report_fingerprints_in_database(self, connection=None):
        try:
            # Create a set to store report fingerprints
            report_fingerprints = set()

            if self.parsing_canceled:
                return report_fingerprints

            self.update_label.emit(
                build_three_line_status(
                    "Parsing reports...",
                    "Loading existing report fingerprints from database",
                    "ETA --",
                )
            )
            self._emit_stage_progress('load_existing_reports', 0.0)

            ensure_characteristic_alias_schema(
                self.db_file,
                connection=connection,
                retries=5,
                retry_delay_s=1,
            )

            table_exists = execute_with_retry(
                self.db_file,
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='REPORTS'",
                connection=connection,
                retries=5,
                retry_delay_s=1,
            )

            if not table_exists:
                self._emit_stage_progress('load_existing_reports', 1.0)
                return report_fingerprints

            matched_rows_by_id = {}
            filename_batches = list(
                self._batched_values(
                    self._report_lookup_candidates.get('filenames', set()),
                    self.LOOKUP_BATCH_SIZE,
                )
            )
            reference_date_batches = list(
                self._batched_values(
                    self._report_lookup_candidates.get('reference_dates', set()),
                    self.LOOKUP_BATCH_SIZE,
                )
            )
            total_batches = max(1, len(filename_batches) + len(reference_date_batches))
            completed_batches = 0

            for filename_batch in filename_batches:
                if self.parsing_canceled:
                    break

                placeholders = ",".join("?" for _ in filename_batch)
                rows = execute_with_retry(
                    self.db_file,
                    (
                        "SELECT ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER "
                        f"FROM REPORTS WHERE FILENAME IN ({placeholders})"
                    ),
                    tuple(filename_batch),
                    connection=connection,
                    retries=5,
                    retry_delay_s=1,
                )
                for row in rows:
                    matched_rows_by_id[row[0] if row[0] is not None else row] = row

                completed_batches += 1
                self._emit_stage_progress('load_existing_reports', completed_batches / total_batches)

            for reference_date_batch in reference_date_batches:
                if self.parsing_canceled:
                    break

                conditions = " OR ".join("(REFERENCE = ? AND DATE = ?)" for _ in reference_date_batch)
                params = tuple(
                    value
                    for reference_value, date_value in reference_date_batch
                    for value in (reference_value, date_value)
                )
                rows = execute_with_retry(
                    self.db_file,
                    (
                        "SELECT ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER "
                        f"FROM REPORTS WHERE {conditions}"
                    ),
                    params,
                    connection=connection,
                    retries=5,
                    retry_delay_s=1,
                )
                for row in rows:
                    matched_rows_by_id[row[0] if row[0] is not None else row] = row

                completed_batches += 1
                self._emit_stage_progress('load_existing_reports', completed_batches / total_batches)

            report_fingerprints.update(
                build_report_fingerprints_from_rows(
                    matched_rows_by_id.values(),
                    should_cancel=lambda: self.parsing_canceled,
                )
            )
            self._emit_stage_progress('load_existing_reports', 1.0)

            # Return report fingerprints from fallback path
            return report_fingerprints
        except Exception as e:
            self.log_and_exit(e)

    def stop_parsing(self):
        try:
            # Set the flag to indicate parsing cancellation
            self.parsing_canceled = True
            logger.info(
                "Parse cancellation requested",
                extra=build_parse_log_extra(
                    source_path=self.directory,
                    cancel_flag=True,
                ),
            )
        except Exception as e:
            self.log_and_exit(e)

    def run(self):
        try:
            list_of_reports = self.get_list_of_reports()
            if self.parsing_canceled:
                logger.info(
                    "Parse ended before processing due to cancellation",
                    extra=build_parse_log_extra(
                        source_path=self.directory,
                        total_files=len(list_of_reports),
                        parsed_count=0,
                        cancel_flag=True,
                    )
                )
                self.parsing_finished.emit()
                return

            with sqlite_connection_scope(self.db_file) as connection:
                report_fingerprints = self.get_report_fingerprints_in_database(connection)

                logger.info(
                    "Parse processing started",
                    extra=build_parse_log_extra(
                        source_path=self.directory,
                        total_files=len(list_of_reports),
                        parsed_count=0,
                        cancel_flag=self.parsing_canceled,
                    ),
                )

                start_time = time.perf_counter()
                telemetry_batch_start = time.perf_counter()
                telemetry_batch_first_index = 1
                telemetry_batch_elapsed_s = 0.0
                telemetry_batch_backend_counts = {}

                def _record_file_telemetry(parser, parsed_files, total_files, parse_duration_s):
                    nonlocal telemetry_batch_start, telemetry_batch_first_index
                    nonlocal telemetry_batch_elapsed_s, telemetry_batch_backend_counts

                    backend = getattr(parser, "parse_backend_used", "unknown")
                    telemetry_batch_elapsed_s += parse_duration_s
                    telemetry_batch_backend_counts[backend] = telemetry_batch_backend_counts.get(backend, 0) + 1

                    completed_batch_size = parsed_files - telemetry_batch_first_index + 1
                    is_batch_boundary = (completed_batch_size >= PARSE_TELEMETRY_BATCH_SIZE) or (parsed_files == total_files)
                    if not is_batch_boundary:
                        return

                    wall_clock_elapsed_s = time.perf_counter() - telemetry_batch_start
                    logger.info(
                        "Parse batch completed",
                        extra=build_parse_log_extra(
                            source_path=self.directory,
                            total_files=total_files,
                            parsed_count=parsed_files,
                            cancel_flag=self.parsing_canceled,
                        )
                        | {
                            "batch_start_index": telemetry_batch_first_index,
                            "batch_end_index": parsed_files,
                            "batch_file_count": completed_batch_size,
                            "batch_parse_elapsed_s": round(telemetry_batch_elapsed_s, 4),
                            "batch_wall_elapsed_s": round(wall_clock_elapsed_s, 4),
                            "batch_avg_parse_s": round(telemetry_batch_elapsed_s / completed_batch_size, 4),
                            "batch_backend_counts": dict(telemetry_batch_backend_counts),
                        },
                    )

                    telemetry_batch_start = time.perf_counter()
                    telemetry_batch_first_index = parsed_files + 1
                    telemetry_batch_elapsed_s = 0.0
                    telemetry_batch_backend_counts = {}

                result = parse_new_reports(
                    list_of_reports,
                    report_fingerprints,
                    parser_factory=lambda report: CMMReportParser(report, self.db_file, connection=connection),
                    persist_report=lambda parser: parser.open_database_and_check_filename(),
                    should_cancel=lambda: self.parsing_canceled,
                    on_progress=lambda parsed_files, total_files: (
                        self._emit_stage_progress('parse_reports', parsed_files / total_files if total_files else 1.0),
                        self.update_label.emit(
                            self._build_parse_label(
                                parsed_files=parsed_files,
                                total_files=total_files,
                                start_time=start_time,
                            )
                        ),
                        logger.debug(
                            "Parse progress update",
                            extra=build_parse_log_extra(
                                source_path=self.directory,
                                total_files=total_files,
                                parsed_count=parsed_files,
                                cancel_flag=self.parsing_canceled,
                            ),
                        ),
                    ),
                    on_file_parsed=_record_file_telemetry,
                )

            if result.total_files == 0:
                self._emit_stage_progress('parse_reports', 1.0)
                self.update_label.emit(
                    build_three_line_status(
                        "Parsing reports...",
                        "No reports found to parse",
                        "ETA 0:00",
                    )
                )

            logger.info(
                "Parse processing finished",
                extra=build_parse_log_extra(
                    source_path=self.directory,
                    total_files=result.total_files,
                    parsed_count=result.parsed_files,
                    cancel_flag=self.parsing_canceled,
                ),
            )

            self.parsing_finished.emit()
        except Exception as e:
            self.log_and_exit(e)
        finally:
            if self._extracted_archive_dir is not None:
                self._extracted_archive_dir.cleanup()
                self._extracted_archive_dir = None
        
    def log_and_exit(self, exception):
        caller = inspect.stack()[1].function
        context = f"parse operation ({caller})"
        logger.error(
            "Parse operation failed",
            extra=build_parse_log_extra(
                source_path=self.directory,
                cancel_flag=self.parsing_canceled,
            ) | {"exception_class": type(exception).__name__, "operation_context": context},
        )
        if hasattr(custom_logger, "handle_exception") and hasattr(custom_logger, "LOG_ONLY"):
            custom_logger.handle_exception(
                exception,
                behavior=custom_logger.LOG_ONLY,
                logger_name=logger.logger.name,
                context=context,
                reraise=False,
            )
        else:
            custom_logger.CustomLogger(exception, reraise=False)
        self.error_occurred.emit(f"{context}: {exception}")

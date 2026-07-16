"""Background parser thread using report_parser_factory to instantiate parser implementations."""

import inspect
import json
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from metroliza.parsing import report_parser_factory
import metroliza.shared.custom_logger as custom_logger
from PyQt6.QtCore import QThread, pyqtSignal
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request
from metroliza.reports.cmm_schema import ensure_cmm_report_schema
from metroliza.reports.db import execute_with_retry, sqlite_connection_scope
from metroliza.shared.env_utils import env_bool, env_int
from metroliza.shared.log_context import build_parse_log_extra, get_operation_logger
from metroliza.shared.progress_status import (
    MonotonicProgressEmitterMixin,
    build_three_line_status,
    format_progress_duration,
)
from metroliza.reports.report_identity import build_report_identity_hash
from metroliza.reports.report_metadata_models import CanonicalReportMetadata
from metroliza.reports.report_repository import ReportRepository, compute_sha256
from metroliza.parsing.base_report_parser import BaseReportParser
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.parser_plugin_contracts import infer_source_format
from metroliza.parsing.source_inspection import SourceInspectionContext
from metroliza.reports.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE


get_parser = report_parser_factory.get_parser


@dataclass(frozen=True)
class ParseBatchResult:
    parsed_files: int
    total_files: int
    failed_files: int = 0
    skipped_files: int = 0


@dataclass(frozen=True)
class MetadataEnrichmentBatchResult:
    enriched_files: int
    total_files: int
    failed_files: int = 0
    skipped_files: int = 0


PARSE_TELEMETRY_BATCH_SIZE = 25


def build_report_fingerprints_from_rows(rows, should_cancel=lambda: False):
    report_fingerprints = set()
    add_fingerprint = report_fingerprints.add

    for row in rows:
        if should_cancel():
            break

        sha256_value = row[0] if not isinstance(row, dict) else row.get('sha256')
        if sha256_value:
            add_fingerprint(f"sha256:{sha256_value}")
    return report_fingerprints


def build_source_file_fingerprint(
    report_path,
    source_inspection: SourceInspectionContext | None = None,
):
    inspection = source_inspection or SourceInspectionContext.from_path(
        report_path,
        source_format=infer_source_format(report_path),
    )
    sha256_value = inspection.sha256
    if sha256_value is None:
        sha256_value = compute_sha256(report_path)
    return f"sha256:{sha256_value}"


def _exception_traceback_text(exception):
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__)).rstrip()


def _format_parser_resolution_diagnostics(diagnostics) -> str:
    selected = diagnostics.selected.plugin_id if diagnostics.selected is not None else "none"
    candidate_parts = []
    for candidate in diagnostics.candidates_considered:
        reasons = ",".join(candidate.reasons) if candidate.reasons else "-"
        warnings = ",".join(candidate.warnings) if candidate.warnings else "-"
        candidate_parts.append(
            f"{candidate.plugin_id}:can_parse={candidate.can_parse}:confidence={candidate.confidence}:"
            f"reasons={reasons}:warnings={warnings}"
        )

    return (
        f"resolver_selected={selected} resolver_rejected_reason={diagnostics.rejected_reason or '-'} "
        f"resolver_candidates=[{'; '.join(candidate_parts) if candidate_parts else '-'}]"
    )


def _parser_resolution_diagnostic_summary(report) -> str:
    try:
        diagnostics = report_parser_factory.resolve_parser_with_diagnostics(report)
    except Exception as exc:  # pragma: no cover - defensive logging path
        return f"resolver_diagnostics_error={type(exc).__name__}: {exc}"
    return _format_parser_resolution_diagnostics(diagnostics)


def _log_unsupported_report_skip(
    report,
    exception,
    processed_files,
    total_files,
    *,
    cancel_flag=False,
):
    resolver_summary = _format_parser_resolution_diagnostics(exception.diagnostics)
    logger.info(
        "Parse skipped unsupported report: file=%s %s",
        report,
        resolver_summary,
        extra=build_parse_log_extra(
            source_path=report,
            total_files=total_files,
            parsed_count=processed_files,
            cancel_flag=cancel_flag,
        )
        | {
            "source_file": str(report),
            "stage": "parser_selection",
            "skip_reason": "unsupported_report_format",
            "parser_resolution": resolver_summary,
        },
    )


def _log_parse_file_failure(report, stage, exception, processed_files, total_files, *, cancel_flag=False):
    exception_class = type(exception).__name__
    exception_message = str(exception)
    traceback_text = _exception_traceback_text(exception)
    resolver_summary = ""
    if str(stage) == "parser":
        diagnostics = getattr(exception, "diagnostics", None)
        if diagnostics is not None:
            resolver_summary = _format_parser_resolution_diagnostics(diagnostics)
        elif exception_class == "ValueError" and "Unsupported report format" in exception_message:
            resolver_summary = _parser_resolution_diagnostic_summary(report)
    resolver_suffix = f" {resolver_summary}" if resolver_summary else ""
    exc_info = (
        (type(exception), exception, exception.__traceback__)
        if exception.__traceback__ is not None
        else None
    )
    logger.warning(
        "Parse report failed: file=%s stage=%s exception=%s message=%s%s",
        report,
        stage,
        exception_class,
        exception_message,
        resolver_suffix,
        exc_info=exc_info,
        extra=build_parse_log_extra(
            source_path=report,
            total_files=total_files,
            parsed_count=processed_files,
            cancel_flag=cancel_flag,
        )
        | {
            "source_file": str(report),
            "stage": str(stage),
            "exception_class": exception_class,
            "exception_message": exception_message,
            "traceback": traceback_text,
            "parser_resolution": resolver_summary,
        },
    )


def parse_new_reports(
    report_paths,
    report_fingerprints,
    parser_factory,
    persist_report,
    should_cancel=lambda: False,
    on_progress=None,
    on_file_parsed=None,
    on_file_failed=None,
    enable_two_stage_pipeline=False,
    worker_count=None,
    log_file_failures=True,
):
    parsed_files = 0
    failed_files = 0
    skipped_files = 0
    total_files = len(report_paths)

    def _emit_processed_progress():
        if on_progress:
            on_progress(parsed_files + failed_files + skipped_files, total_files)

    def _record_unsupported_skip(report, exception):
        nonlocal skipped_files
        skipped_files += 1
        processed_files = parsed_files + failed_files + skipped_files
        _log_unsupported_report_skip(
            report,
            exception,
            processed_files,
            total_files,
        )
        _emit_processed_progress()

    def _record_file_failure(report, stage, exception):
        nonlocal failed_files
        failed_files += 1
        processed_files = parsed_files + failed_files + skipped_files
        setattr(exception, "_metroliza_parse_failure_stage", str(stage))
        if log_file_failures:
            _log_parse_file_failure(
                report,
                stage,
                exception,
                processed_files,
                total_files,
            )
        if on_file_failed:
            on_file_failed(report, exception, processed_files, total_files)
        _emit_processed_progress()

    if enable_two_stage_pipeline:
        max_workers = worker_count or max(1, min(8, os.cpu_count() or 1))

        def _stage1_worker(report, enqueued_at, source_inspection):
            try:
                parser = report_parser_factory.invoke_parser_factory(
                    parser_factory,
                    report,
                    source_inspection=source_inspection,
                )
            except Exception as exc:
                setattr(exc, "_metroliza_parse_failure_stage", "parser")
                raise
            stage_timings = getattr(parser, "stage_timings_s", None)
            if isinstance(stage_timings, dict):
                stage_timings["stage1_queue_wait_s"] = max(0.0, time.perf_counter() - enqueued_at)

            prepare_method = getattr(parser, "prepare_for_two_stage_pipeline", None)
            if callable(prepare_method):
                try:
                    prepare_method()
                except Exception as exc:
                    setattr(exc, "_metroliza_parse_failure_stage", "prepare")
                    raise

            return parser, time.perf_counter()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for report in report_paths:
                if should_cancel():
                    break
                source_inspection = SourceInspectionContext.from_path(
                    report,
                    source_format=infer_source_format(report),
                )
                fingerprint = build_source_file_fingerprint(report, source_inspection)
                if fingerprint in report_fingerprints:
                    parsed_files += 1
                    _emit_processed_progress()
                    continue
                enqueued_at = time.perf_counter()
                futures.append(
                    (
                        report,
                        fingerprint,
                        executor.submit(
                            _stage1_worker,
                            report,
                            enqueued_at,
                            source_inspection,
                        ),
                    )
                )

            future_context = {future: (report, fingerprint) for report, fingerprint, future in futures}
            for future in as_completed(future_context):
                if should_cancel():
                    break

                report_parse_start = time.perf_counter()
                report, fingerprint = future_context[future]
                try:
                    parser, stage1_completed_at = future.result()
                except report_parser_factory.UnsupportedReportFormatError as exc:
                    _record_unsupported_skip(report, exc)
                    continue
                except Exception as exc:
                    _record_file_failure(
                        report,
                        getattr(exc, "_metroliza_parse_failure_stage", "parser"),
                        exc,
                    )
                    continue

                stage_timings = getattr(parser, "stage_timings_s", None)
                if isinstance(stage_timings, dict):
                    stage_timings["stage2_queue_wait_s"] = max(0.0, time.perf_counter() - stage1_completed_at)

                if fingerprint not in report_fingerprints:
                    try:
                        persist_report(parser)
                    except Exception as exc:
                        _record_file_failure(report, "persistence", exc)
                        continue
                    report_fingerprints.add(fingerprint)

                parsed_files += 1
                parse_duration_s = time.perf_counter() - report_parse_start

                if on_file_parsed:
                    on_file_parsed(parser, parsed_files, total_files, parse_duration_s)

                _emit_processed_progress()

            for _, _, future in futures:
                if not future.done():
                    future.cancel()

        return ParseBatchResult(
            parsed_files=parsed_files,
            total_files=total_files,
            failed_files=failed_files,
            skipped_files=skipped_files,
        )

    for report in report_paths:
        if should_cancel():
            break

        report_parse_start = time.perf_counter()
        source_inspection = SourceInspectionContext.from_path(
            report,
            source_format=infer_source_format(report),
        )
        fingerprint = build_source_file_fingerprint(report, source_inspection)
        if fingerprint not in report_fingerprints:
            try:
                parser = report_parser_factory.invoke_parser_factory(
                    parser_factory,
                    report,
                    source_inspection=source_inspection,
                )
            except report_parser_factory.UnsupportedReportFormatError as exc:
                _record_unsupported_skip(report, exc)
                continue
            except Exception as exc:
                _record_file_failure(report, "parser", exc)
                continue

            try:
                persist_report(parser)
            except Exception as exc:
                _record_file_failure(report, "persistence", exc)
                continue
            report_fingerprints.add(fingerprint)
        else:
            parser = None
        parsed_files += 1
        parse_duration_s = time.perf_counter() - report_parse_start

        if on_file_parsed:
            on_file_parsed(parser, parsed_files, total_files, parse_duration_s)

        _emit_processed_progress()

    return ParseBatchResult(
        parsed_files=parsed_files,
        total_files=total_files,
        failed_files=failed_files,
        skipped_files=skipped_files,
    )


def enrich_report_metadata(
    report_paths,
    parser_factory,
    persist_enrichment,
    should_cancel=lambda: False,
    on_progress=None,
    on_file_enriched=None,
    on_warning=None,
):
    enriched_files = 0
    failed_files = 0
    skipped_files = 0
    processed_files = 0
    total_files = len(report_paths)

    for report in report_paths:
        if should_cancel():
            break

        enrichment_start = time.perf_counter()
        parser = None
        try:
            source_inspection = SourceInspectionContext.from_path(
                report,
                source_format=infer_source_format(report),
            )
            parser = report_parser_factory.invoke_parser_factory(
                parser_factory,
                report,
                source_inspection=source_inspection,
            )
            verified_source_sha256 = source_inspection.verified_sha256()
            try:
                parser._verified_source_sha256 = verified_source_sha256
            except (AttributeError, TypeError):
                pass
            enriched = parser is not None and persist_enrichment(report, parser)
        except report_parser_factory.UnsupportedReportFormatError as exc:
            skipped_files += 1
            _log_unsupported_report_skip(
                report,
                exc,
                processed_files + 1,
                total_files,
            )
        except Exception as exc:
            failed_files += 1
            logger.warning(
                "Metadata enrichment skipped failed report",
                extra={
                    "source_path": str(report),
                    "error_class": type(exc).__name__,
                },
                exc_info=True,
            )
            if on_warning:
                on_warning(report, exc)
        else:
            if enriched:
                enriched_files += 1
            else:
                skipped_files += 1

        processed_files += 1
        enrichment_duration_s = time.perf_counter() - enrichment_start

        if on_file_enriched:
            on_file_enriched(parser, processed_files, total_files, enrichment_duration_s)

        if on_progress:
            on_progress(processed_files, total_files)

    return MetadataEnrichmentBatchResult(
        enriched_files=enriched_files,
        total_files=total_files,
        failed_files=failed_files,
        skipped_files=skipped_files,
    )


logger = get_operation_logger(logging.getLogger(__name__), "parse_reports")

_REPORT_EXTENSIONS_BY_SOURCE_FORMAT = {
    "pdf": {".pdf"},
    "excel": {".xls", ".xlsx"},
    "csv": {".csv"},
}
_CURRENT_CMM_METADATA_PARSER_ID = DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id
_CURRENT_CMM_PARSER_VERSION = getattr(getattr(CMMReportParser, "manifest", None), "version", "1.1.0")


def supported_report_file_extensions() -> set[str]:
    """Return suffixes supported by registered parser manifests."""

    try:
        report_parser_factory.load_external_plugins()
    except Exception:
        logger.warning("Could not load external parser plugins during discovery", exc_info=True)

    extensions = set(_REPORT_EXTENSIONS_BY_SOURCE_FORMAT["pdf"])
    for manifest in report_parser_factory.list_plugins():
        for source_format in getattr(manifest, "supported_formats", ()) or ():
            extensions.update(_REPORT_EXTENSIONS_BY_SOURCE_FORMAT.get(str(source_format).lower(), ()))
    return extensions


_METADATA_VALUE_FIELDS = (
    "reference",
    "reference_raw",
    "report_date",
    "report_time",
    "part_name",
    "revision",
    "sample_number",
    "sample_number_kind",
    "stats_count_raw",
    "stats_count_int",
    "operator_name",
    "comment",
)
_OCR_ONLY_METADATA_FIELDS = frozenset({"report_time", "revision", "operator_name", "comment"})
_FIELD_DEPENDENCIES = {
    "reference": ("reference_raw",),
    "sample_number": ("sample_number_kind",),
    "stats_count_raw": ("stats_count_int",),
}


def _json_object(value):
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _metadata_value(metadata, field_name):
    if isinstance(metadata, dict):
        return metadata.get(field_name)
    return getattr(metadata, field_name, None)


def _metadata_mapping(metadata):
    return {field_name: _metadata_value(metadata, field_name) for field_name in _METADATA_VALUE_FIELDS}


def _field_has_manual_override(metadata_json, field_name):
    manual_overrides = metadata_json.get("manual_overrides") if isinstance(metadata_json, dict) else {}
    return isinstance(manual_overrides, dict) and field_name in manual_overrides


def _should_use_enriched_metadata_field(field_name, current_value, enriched_value, current_metadata_json):
    if _field_has_manual_override(current_metadata_json, field_name):
        return False
    if enriched_value in (None, ""):
        return False
    if current_value in (None, ""):
        return True
    if current_value == enriched_value:
        return True
    return field_name in _OCR_ONLY_METADATA_FIELDS


def merge_enriched_metadata_for_persistence(current_row, enriched_metadata):
    """Merge complete metadata into an existing light row without replacing stable light fields."""

    current_row = current_row or {}
    current_metadata_json = _json_object(current_row.get("metadata_json"))
    enriched_metadata_json = _json_object(_metadata_value(enriched_metadata, "metadata_json"))
    enriched_map = _metadata_mapping(enriched_metadata)
    merged_map = dict(enriched_map)
    updated_fields = []
    preserved_fields = []

    for field_name in _METADATA_VALUE_FIELDS:
        current_value = current_row.get(field_name)
        enriched_value = enriched_map.get(field_name)
        if _should_use_enriched_metadata_field(field_name, current_value, enriched_value, current_metadata_json):
            if current_value != enriched_value:
                updated_fields.append(field_name)
            continue

        if current_value not in (None, ""):
            merged_map[field_name] = current_value
            if current_value != enriched_value:
                preserved_fields.append(field_name)

            for dependent_field in _FIELD_DEPENDENCIES.get(field_name, ()):
                dependent_value = current_row.get(dependent_field)
                if dependent_value not in (None, ""):
                    merged_map[dependent_field] = dependent_value
                    if dependent_value != enriched_map.get(dependent_field):
                        preserved_fields.append(dependent_field)

    merged_metadata_json = dict(enriched_metadata_json)
    current_manual_overrides = current_metadata_json.get("manual_overrides")
    if isinstance(current_manual_overrides, dict) and current_manual_overrides:
        merged_metadata_json["manual_overrides"] = current_manual_overrides

    field_sources = dict(merged_metadata_json.get("field_sources") or {})
    current_field_sources = current_metadata_json.get("field_sources")
    if isinstance(current_field_sources, dict):
        for field_name in preserved_fields:
            source = current_field_sources.get(field_name)
            if source is not None:
                field_sources[field_name] = source
    merged_metadata_json["field_sources"] = field_sources
    merged_metadata_json["metadata_enrichment"] = {
        "mode": "complete",
        "merge_policy": "preserve_existing_nonempty_light_fields_except_ocr_only",
        "preserved_fields": sorted(set(preserved_fields)),
        "updated_fields": sorted(set(updated_fields)),
    }

    merged_metadata = CanonicalReportMetadata(
        parser_id=_metadata_value(enriched_metadata, "parser_id"),
        template_family=_metadata_value(enriched_metadata, "template_family"),
        template_variant=_metadata_value(enriched_metadata, "template_variant"),
        metadata_confidence=_metadata_value(enriched_metadata, "metadata_confidence") or 0.0,
        reference=merged_map.get("reference"),
        reference_raw=merged_map.get("reference_raw"),
        report_date=merged_map.get("report_date"),
        report_time=merged_map.get("report_time"),
        part_name=merged_map.get("part_name"),
        revision=merged_map.get("revision"),
        sample_number=merged_map.get("sample_number"),
        sample_number_kind=merged_map.get("sample_number_kind"),
        stats_count_raw=merged_map.get("stats_count_raw"),
        stats_count_int=merged_map.get("stats_count_int"),
        operator_name=merged_map.get("operator_name"),
        comment=merged_map.get("comment"),
        page_count=_metadata_value(enriched_metadata, "page_count"),
        metadata_json=merged_metadata_json,
        warnings=tuple(_metadata_value(enriched_metadata, "warnings") or ()),
    )
    merge_summary = {
        "preserved_fields": sorted(set(preserved_fields)),
        "updated_fields": sorted(set(updated_fields)),
    }
    return merged_metadata, merge_summary


def report_metadata_row_for_enrichment(db_file, report_id, *, connection=None):
    rows = execute_with_retry(
        db_file,
        """
        SELECT
            pr.raw_report_json,
            rm.reference,
            rm.reference_raw,
            rm.report_date,
            rm.report_time,
            rm.part_name,
            rm.revision,
            rm.sample_number,
            rm.sample_number_kind,
            rm.stats_count_raw,
            rm.stats_count_int,
            rm.operator_name,
            rm.comment,
            rm.metadata_json
        FROM parsed_reports pr
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        WHERE pr.id = ?
        """,
        params=(int(report_id),),
        connection=connection,
        retries=5,
        retry_delay_s=1,
    )
    if not rows:
        return {}
    columns = (
        "raw_report_json",
        "reference",
        "reference_raw",
        "report_date",
        "report_time",
        "part_name",
        "revision",
        "sample_number",
        "sample_number_kind",
        "stats_count_raw",
        "stats_count_int",
        "operator_name",
        "comment",
        "metadata_json",
    )
    return dict(zip(columns, rows[0]))


def selection_result_for_complete_metadata_parser(parser):
    if hasattr(parser, "metadata_parsing_mode"):
        parser.metadata_parsing_mode = "complete"
    parser.open_report()
    selection_result = getattr(parser, "_metadata_selection_result", None)
    if selection_result is None:
        extract_metadata = getattr(type(parser), "extract_metadata", None)
        if extract_metadata is None or extract_metadata is BaseReportParser.extract_metadata:
            return None
        selection_result = parser.extract_metadata()
    return selection_result


def persist_complete_metadata_enrichment(db_file, report_id, selection_result, *, connection=None):
    if selection_result is None:
        return None, {"skipped": True, "reason": "metadata_parser_not_available"}
    current_row = report_metadata_row_for_enrichment(db_file, report_id, connection=connection)
    merged_metadata, merge_summary = merge_enriched_metadata_for_persistence(
        current_row,
        selection_result.metadata,
    )
    raw_report_json = _json_object(current_row.get("raw_report_json"))
    raw_report_json["metadata_enrichment"] = {
        "mode": "complete",
        "measurement_rows_preserved": True,
        **merge_summary,
    }
    repository = ReportRepository(db_file, connection=connection)
    repository.replace_report_metadata_enrichment(
        report_id,
        merged_metadata,
        candidates=selection_result.candidates,
        warnings=merged_metadata.warnings,
        metadata_version="report_metadata_v1",
        metadata_profile_id=DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.template_family,
        metadata_profile_version="1",
        parse_status="parsed_with_warnings" if merged_metadata.warnings else "parsed",
        metadata_confidence=merged_metadata.metadata_confidence,
        identity_hash=build_report_identity_hash(merged_metadata),
        raw_report_json=raw_report_json,
    )
    return merged_metadata, merge_summary


class ParseReportsThread(MonotonicProgressEmitterMixin, QThread):
    LOOKUP_BATCH_SIZE = 250
    PROGRESS_STAGE_RANGES = {
        'discover_reports': (0, 15),
        'load_existing_reports': (15, 30),
        'parse_reports': (30, 100),
        'enrich_metadata': (100, 100),
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
        self.metadata_parsing_mode = validated_request.metadata_parsing_mode
        self.run_background_metadata_enrichment = validated_request.run_background_metadata_enrichment
        self.parsing_canceled = False
        self._extracted_archive_dir = None
        self.last_parse_result = ParseBatchResult(parsed_files=0, total_files=0)
        self._last_emitted_progress = -1
        self._progress_stage_ranges = dict(self.PROGRESS_STAGE_RANGES)
        if self.run_background_metadata_enrichment and self.metadata_parsing_mode == "light":
            self._progress_stage_ranges["parse_reports"] = (30, 75)
            self._progress_stage_ranges["enrich_metadata"] = (75, 100)

    def _emit_stage_progress(self, stage_name, fraction=1.0):
        start, end = self._progress_stage_ranges[stage_name]
        safe_fraction = max(0.0, min(1.0, float(fraction)))
        self._emit_progress(start + ((end - start) * safe_fraction))

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
        elapsed_display = format_progress_duration(elapsed_seconds)
        eta_display = format_progress_duration(eta_seconds)
        return build_three_line_status(stage_line, detail_line, f"{elapsed_display} elapsed, ETA {eta_display}")

    def _build_enrichment_label(self, *, enriched_files, total_files, start_time):
        stage_line = "Enriching report metadata..."
        if total_files <= 0:
            return build_three_line_status(stage_line, "Files remaining 0", "ETA --")

        remaining_files = max(0, total_files - enriched_files)
        detail_line = f"File {enriched_files}/{total_files}, remaining {remaining_files}"

        elapsed_seconds = max(0.0, time.perf_counter() - start_time)
        if enriched_files < 2 or elapsed_seconds < 1.0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        files_per_second = enriched_files / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if files_per_second <= 0:
            return build_three_line_status(stage_line, detail_line, "ETA --")

        eta_seconds = remaining_files / files_per_second
        elapsed_display = format_progress_duration(elapsed_seconds)
        eta_display = format_progress_duration(eta_seconds)
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
            report_files = []
            report_root = self._resolve_report_root()
            supported_extensions = supported_report_file_extensions()
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
            candidates = (report_root,) if report_root.is_file() else report_root.rglob("*")
            for path in candidates:
                if self.parsing_canceled:
                    break
                if (
                    path.is_file()
                    and path.suffix.lower() in supported_extensions
                    and path.stat().st_size
                ):
                    report_files.append(path)

            self._emit_stage_progress('discover_reports', 1.0)
            logger.info(
                "Parse discovery finished",
                extra=build_parse_log_extra(
                    source_path=report_root,
                    total_files=len(report_files),
                    parsed_count=0,
                    cancel_flag=self.parsing_canceled,
                ),
            )
            return report_files
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

            table_exists = execute_with_retry(
                self.db_file,
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_files'",
                connection=connection,
                retries=5,
                retry_delay_s=1,
            )

            if not table_exists:
                self._emit_stage_progress('load_existing_reports', 1.0)
                return report_fingerprints

            if self.metadata_parsing_mode == "light":
                rows = execute_with_retry(
                    self.db_file,
                    """
                    SELECT sf.sha256
                    FROM source_files sf
                    JOIN parsed_reports pr ON pr.source_file_id = sf.id
                    WHERE sf.is_active = 1
                      AND (
                        pr.parser_id <> ?
                        OR pr.parser_version = ?
                      )
                    """,
                    params=(
                        _CURRENT_CMM_METADATA_PARSER_ID,
                        _CURRENT_CMM_PARSER_VERSION,
                    ),
                    connection=connection,
                    retries=5,
                    retry_delay_s=1,
                )
            else:
                rows = execute_with_retry(
                    self.db_file,
                    """
                    SELECT sf.sha256
                    FROM source_files sf
                    JOIN parsed_reports pr ON pr.source_file_id = sf.id
                    LEFT JOIN report_parse_state rps ON rps.report_id = pr.id
                    WHERE sf.is_active = 1
                      AND (
                        pr.parser_id <> ?
                        OR (
                          pr.parser_version = ?
                          AND rps.header_extraction_mode IS NOT NULL
                          AND rps.header_extraction_mode <> 'none'
                          AND rps.header_ocr_error_code IS NULL
                          AND COALESCE(rps.reference_source, '') <> 'filename_candidate'
                          AND COALESCE(rps.report_date_source, '') <> 'filename_candidate'
                          AND COALESCE(rps.stats_count_source, '') <> 'filename_candidate'
                        )
                      )
                    """,
                    params=(
                        _CURRENT_CMM_METADATA_PARSER_ID,
                        _CURRENT_CMM_PARSER_VERSION,
                    ),
                    connection=connection,
                    retries=5,
                    retry_delay_s=1,
                )
            report_fingerprints.update(
                build_report_fingerprints_from_rows(rows, should_cancel=lambda: self.parsing_canceled)
            )
            self._emit_stage_progress('load_existing_reports', 1.0)

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

    def _report_id_for_source_path(
        self,
        report_path,
        connection=None,
        *,
        source_sha256=None,
    ):
        sha256_value = source_sha256 or compute_sha256(report_path)
        rows = execute_with_retry(
            self.db_file,
            """
            SELECT pr.id
            FROM source_files sf
            JOIN parsed_reports pr ON pr.source_file_id = sf.id
            WHERE sf.sha256 = ?
              AND sf.is_active = 1
            ORDER BY pr.id DESC
            LIMIT 1
            """,
            params=(sha256_value,),
            connection=connection,
            retries=5,
            retry_delay_s=1,
        )
        if not rows:
            return None
        return int(rows[0][0])

    def _report_metadata_row(self, report_id, connection=None):
        return report_metadata_row_for_enrichment(self.db_file, report_id, connection=connection)

    def _run_background_metadata_enrichment(self, report_paths, connection):
        if self.metadata_parsing_mode != "light" or not self.run_background_metadata_enrichment:
            return MetadataEnrichmentBatchResult(enriched_files=0, total_files=0)

        if not report_paths:
            self._emit_stage_progress('enrich_metadata', 1.0)
            return MetadataEnrichmentBatchResult(enriched_files=0, total_files=0)

        self.update_label.emit(
            build_three_line_status(
                "Enriching report metadata...",
                "Running complete OCR metadata for imported reports",
                "ETA --",
            )
        )
        self._emit_stage_progress('enrich_metadata', 0.0)

        start_time = time.perf_counter()

        def _parser_factory(report, *, source_inspection=None):
            parser = get_parser(
                report,
                self.db_file,
                connection=connection,
                source_inspection=source_inspection,
            )
            selection_result = selection_result_for_complete_metadata_parser(parser)
            if selection_result is not None:
                parser._metadata_selection_result = selection_result
            return parser

        def _persist_enrichment(report, parser):
            report_id = self._report_id_for_source_path(
                report,
                connection=connection,
                source_sha256=getattr(parser, "_verified_source_sha256", None),
            )
            if report_id is None:
                return False

            selection_result = getattr(parser, "_metadata_selection_result", None)
            if selection_result is None:
                selection_result = selection_result_for_complete_metadata_parser(parser)
            if selection_result is None:
                return False
            persist_complete_metadata_enrichment(
                self.db_file,
                report_id,
                selection_result,
                connection=connection,
            )
            return True

        result = enrich_report_metadata(
            report_paths,
            parser_factory=_parser_factory,
            persist_enrichment=_persist_enrichment,
            should_cancel=lambda: self.parsing_canceled,
            on_progress=lambda enriched_files, total_files: (
                self._emit_stage_progress('enrich_metadata', enriched_files / total_files if total_files else 1.0),
                self.update_label.emit(
                    self._build_enrichment_label(
                        enriched_files=enriched_files,
                        total_files=total_files,
                        start_time=start_time,
                    )
                ),
            ),
        )
        logger.info(
            "Background metadata enrichment finished",
            extra=build_parse_log_extra(
                source_path=self.directory,
                total_files=result.total_files,
                parsed_count=result.enriched_files,
                cancel_flag=self.parsing_canceled,
            ),
        )
        return result

    def run(self):
        try:
            list_of_reports = self.get_list_of_reports()
            if self.parsing_canceled:
                self.last_parse_result = ParseBatchResult(
                    parsed_files=0,
                    total_files=len(list_of_reports),
                )
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
                ensure_cmm_report_schema(
                    self.db_file,
                    connection=connection,
                    retries=5,
                    retry_delay_s=1,
                )
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
                telemetry_batch_persistence_backend_counts = {}
                telemetry_batch_stage_timing_totals = {}

                def _rate_snapshot(counts):
                    total = sum(counts.values())
                    if total <= 0:
                        return {}
                    return {backend: round(count / total, 4) for backend, count in sorted(counts.items())}

                def _record_file_telemetry(parser, parsed_files, total_files, parse_duration_s):
                    nonlocal telemetry_batch_start, telemetry_batch_first_index
                    nonlocal telemetry_batch_elapsed_s, telemetry_batch_backend_counts
                    nonlocal telemetry_batch_persistence_backend_counts
                    nonlocal telemetry_batch_stage_timing_totals

                    backend = getattr(parser, "parse_backend_used", "unknown")
                    persistence_backend = getattr(parser, "persistence_backend_used", "unknown")
                    telemetry_batch_elapsed_s += parse_duration_s
                    telemetry_batch_backend_counts[backend] = telemetry_batch_backend_counts.get(backend, 0) + 1
                    telemetry_batch_persistence_backend_counts[persistence_backend] = telemetry_batch_persistence_backend_counts.get(persistence_backend, 0) + 1
                    stage_timings = getattr(parser, "stage_timings_s", {})
                    if isinstance(stage_timings, dict):
                        for timing_name, timing_value in stage_timings.items():
                            if isinstance(timing_value, (int, float)):
                                telemetry_batch_stage_timing_totals[timing_name] = telemetry_batch_stage_timing_totals.get(timing_name, 0.0) + float(timing_value)

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
                            "batch_backend_rates": _rate_snapshot(telemetry_batch_backend_counts),
                            "batch_persistence_backend_counts": dict(telemetry_batch_persistence_backend_counts),
                            "batch_persistence_backend_rates": _rate_snapshot(telemetry_batch_persistence_backend_counts),
                            "batch_stage_timing_totals_s": {
                                key: round(value, 4) for key, value in sorted(telemetry_batch_stage_timing_totals.items())
                            },
                            "batch_stage_timing_avg_s": {
                                key: round(value / completed_batch_size, 4)
                                for key, value in sorted(telemetry_batch_stage_timing_totals.items())
                            },
                        },
                    )

                    telemetry_batch_start = time.perf_counter()
                    telemetry_batch_first_index = parsed_files + 1
                    telemetry_batch_elapsed_s = 0.0
                    telemetry_batch_backend_counts = {}
                    telemetry_batch_persistence_backend_counts = {}
                    telemetry_batch_stage_timing_totals = {}

                def _record_file_failure(report, exception, processed_files, total_files):
                    _log_parse_file_failure(
                        report,
                        getattr(exception, "_metroliza_parse_failure_stage", "unknown"),
                        exception,
                        processed_files,
                        total_files,
                        cancel_flag=self.parsing_canceled,
                    )

                two_stage_enabled = env_bool("METROLIZA_PARSE_TWO_STAGE_PIPELINE", default=False)
                try:
                    two_stage_workers = env_int("METROLIZA_PARSE_TWO_STAGE_WORKERS", default=0) or None
                except ValueError:
                    two_stage_workers = None

                def _persist_report(parser):
                    if two_stage_enabled and callable(getattr(parser, "persist_prepared_report", None)):
                        return parser.persist_prepared_report()
                    return parser.open_database_and_check_filename()

                def _parser_factory(report, *, source_inspection=None):
                    return get_parser(
                        report,
                        self.db_file,
                        connection=connection,
                        metadata_parsing_mode=self.metadata_parsing_mode,
                        source_inspection=source_inspection,
                    )

                result = parse_new_reports(
                    list_of_reports,
                    report_fingerprints,
                    parser_factory=_parser_factory,
                    persist_report=_persist_report,
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
                    on_file_failed=_record_file_failure,
                    enable_two_stage_pipeline=two_stage_enabled,
                    worker_count=two_stage_workers,
                    log_file_failures=False,
                )
                self.last_parse_result = result

                if not self.parsing_canceled and self.run_background_metadata_enrichment:
                    self._run_background_metadata_enrichment(list_of_reports, connection)

            if result.total_files == 0:
                self._emit_stage_progress('parse_reports', 1.0)
                self.update_label.emit(
                    build_three_line_status(
                        "Parsing reports...",
                        "No supported report files found in the selected source",
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

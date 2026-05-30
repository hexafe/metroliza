"""Standalone OCR metadata enrichment over existing report databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.reports.cmm_schema import ensure_cmm_report_schema
from metroliza.shared import custom_logger
from metroliza.reports.db import execute_with_retry, sqlite_connection_scope
from metroliza.parsing.parse_reports_thread import (
    MetadataEnrichmentBatchResult,
    persist_complete_metadata_enrichment,
    selection_result_for_complete_metadata_parser,
)
from metroliza.shared.progress_status import build_three_line_status, format_progress_duration
from metroliza.reports.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE
from metroliza.reports.report_parser_factory import get_parser


logger = logging.getLogger(__name__)

_CURRENT_CMM_PARSER_VERSION = getattr(getattr(CMMReportParser, "manifest", None), "version", "1.1.0")
_OCR_ONLY_FIELDS = ("report_time", "revision", "operator_name", "comment")
_CURRENT_METADATA_ENRICHMENT_MODE = "complete"


@dataclass(frozen=True)
class MetadataEnrichmentWorkItem:
    report_id: int
    source_path: str
    sha256: str


def _json_object(value):
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _needs_complete_metadata_enrichment(row):
    metadata_json = _json_object(row["metadata_json"])
    enrichment = metadata_json.get("metadata_enrichment")
    already_enriched = (
        isinstance(enrichment, dict)
        and enrichment.get("mode") == _CURRENT_METADATA_ENRICHMENT_MODE
    )
    parser_current = (
        row["parser_id"] == DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id
        and row["parser_version"] == _CURRENT_CMM_PARSER_VERSION
    )
    missing_ocr_only_field = any(row.get(field_name) in (None, "") for field_name in _OCR_ONLY_FIELDS)
    light_metadata_marker = (
        metadata_json.get("header_ocr_skipped") == "light_metadata_mode"
        or metadata_json.get("metadata_parsing_mode") == "light"
        or metadata_json.get("header_extraction_mode") == "none"
    )
    return (
        not parser_current
        or not already_enriched
        or missing_ocr_only_field
        or light_metadata_marker
    )


def discover_metadata_enrichment_work(db_file, *, connection=None, limit=None):
    """Return existing DB reports whose metadata still benefits from OCR enrichment."""

    params: list[object] = [int(limit) if limit is not None else None]

    rows = execute_with_retry(
        db_file,
        """
        SELECT
            pr.id,
            selected_location.absolute_path,
            sf.sha256,
            pr.parser_id,
            pr.parser_version,
            rm.report_time,
            rm.revision,
            rm.operator_name,
            rm.comment,
            rm.metadata_json
        FROM parsed_reports pr
        JOIN source_files sf ON sf.id = pr.source_file_id
        LEFT JOIN report_metadata rm ON rm.report_id = pr.id
        LEFT JOIN source_file_locations selected_location ON selected_location.id = (
            SELECT sfl.id
            FROM source_file_locations sfl
            WHERE sfl.source_file_id = sf.id
              AND sfl.is_active = 1
            ORDER BY sfl.discovered_at DESC, sfl.id DESC
            LIMIT 1
        )
        WHERE selected_location.absolute_path IS NOT NULL
        ORDER BY pr.id
        LIMIT COALESCE(?, -1)
        """,
        params=tuple(params),
        connection=connection,
        retries=5,
        retry_delay_s=1,
    )
    columns = (
        "report_id",
        "source_path",
        "sha256",
        "parser_id",
        "parser_version",
        "report_time",
        "revision",
        "operator_name",
        "comment",
        "metadata_json",
    )
    work_items = []
    for row in rows:
        row_payload = dict(zip(columns, row))
        if _needs_complete_metadata_enrichment(row_payload):
            work_items.append(
                MetadataEnrichmentWorkItem(
                    report_id=int(row_payload["report_id"]),
                    source_path=str(row_payload["source_path"]),
                    sha256=str(row_payload["sha256"]),
                )
            )
    return work_items


def enrich_existing_report_metadata(db_file, work_item, *, connection=None, parser_factory=None):
    """Run complete metadata extraction for one existing report and persist metadata only."""

    source_path = Path(work_item.source_path)
    if not source_path.is_file():
        return False

    parser_factory = parser_factory or get_parser
    parser = parser_factory(str(source_path), db_file, connection=connection)
    selection_result = selection_result_for_complete_metadata_parser(parser)
    persist_complete_metadata_enrichment(
        db_file,
        work_item.report_id,
        selection_result,
        connection=connection,
    )
    return True


def run_metadata_enrichment_batch(
    db_file,
    work_items,
    *,
    connection=None,
    parser_factory=None,
    should_cancel=lambda: False,
    on_progress=None,
    on_item_enriched=None,
    on_warning=None,
):
    enriched_files = 0
    failed_files = 0
    skipped_files = 0
    processed_files = 0
    total_files = len(work_items)

    for work_item in work_items:
        if should_cancel():
            break
        started_at = time.perf_counter()
        enriched = False
        try:
            enriched = enrich_existing_report_metadata(
                db_file,
                work_item,
                connection=connection,
                parser_factory=parser_factory,
            )
        except Exception as exc:
            failed_files += 1
            logger.warning(
                "Metadata enrichment skipped failed report",
                extra={
                    "report_id": work_item.report_id,
                    "source_path": work_item.source_path,
                    "error_class": type(exc).__name__,
                },
                exc_info=True,
            )
            if on_warning:
                on_warning(work_item, exc)
        else:
            if enriched:
                enriched_files += 1
            else:
                skipped_files += 1
        processed_files += 1
        if on_item_enriched and enriched:
            on_item_enriched(work_item, processed_files, total_files, time.perf_counter() - started_at)
        if on_progress:
            on_progress(processed_files, total_files)

    return MetadataEnrichmentBatchResult(
        enriched_files=enriched_files,
        total_files=total_files,
        failed_files=failed_files,
        skipped_files=skipped_files,
    )


class MetadataEnrichmentThread(QThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    item_enriched = pyqtSignal(int, str)
    warning = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    enrichment_finished = pyqtSignal()

    def __init__(self, db_file, *, limit=None):
        super().__init__()
        self.db_file = str(db_file)
        self.limit = limit
        self.enrichment_canceled = False
        self.result = MetadataEnrichmentBatchResult(enriched_files=0, total_files=0)

    def stop_enrichment(self):
        self.enrichment_canceled = True

    def _build_label(self, *, processed_files, total_files, start_time):
        if total_files <= 0:
            return build_three_line_status("Metadata enrichment", "No reports need enrichment", "ETA 0:00")
        remaining_files = max(0, total_files - processed_files)
        detail_line = f"File {processed_files}/{total_files}, remaining {remaining_files}"
        elapsed_seconds = max(0.0, time.perf_counter() - start_time)
        if processed_files < 2 or elapsed_seconds < 1.0:
            return build_three_line_status("Enriching report metadata...", detail_line, "ETA --")
        files_per_second = processed_files / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if files_per_second <= 0:
            return build_three_line_status("Enriching report metadata...", detail_line, "ETA --")
        elapsed_display = format_progress_duration(elapsed_seconds)
        eta_display = format_progress_duration(remaining_files / files_per_second)
        return build_three_line_status(
            "Enriching report metadata...",
            detail_line,
            f"{elapsed_display} elapsed, ETA {eta_display}",
        )

    def run(self):
        try:
            self.update_label.emit(
                build_three_line_status("Metadata enrichment", "Finding reports to enrich", "ETA --")
            )
            self.update_progress.emit(0)
            with sqlite_connection_scope(self.db_file) as connection:
                ensure_cmm_report_schema(self.db_file, connection=connection, retries=5, retry_delay_s=1)
                work_items = discover_metadata_enrichment_work(
                    self.db_file,
                    connection=connection,
                    limit=self.limit,
                )
                if not work_items:
                    self.update_label.emit(self._build_label(processed_files=0, total_files=0, start_time=time.perf_counter()))
                    self.update_progress.emit(100)
                    self.result = MetadataEnrichmentBatchResult(enriched_files=0, total_files=0)
                    self.enrichment_finished.emit()
                    return

                start_time = time.perf_counter()

                def _on_progress(processed, total):
                    self.update_progress.emit(int(round((processed / total) * 100)) if total else 100)
                    self.update_label.emit(
                        self._build_label(
                            processed_files=processed,
                            total_files=total,
                            start_time=start_time,
                        )
                    )

                def _on_item(work_item, _processed, _total, _duration_s):
                    self.item_enriched.emit(int(work_item.report_id), work_item.source_path)

                def _on_warning(work_item, exc):
                    self.warning.emit(
                        f"Metadata enrichment skipped report {work_item.report_id}: {exc}"
                    )

                self.result = run_metadata_enrichment_batch(
                    self.db_file,
                    work_items,
                    connection=connection,
                    should_cancel=lambda: self.enrichment_canceled,
                    on_progress=_on_progress,
                    on_item_enriched=_on_item,
                    on_warning=_on_warning,
                )
            self.enrichment_finished.emit()
        except Exception as exc:
            logger.exception("Metadata enrichment failed: %s", exc)
            self.error_occurred.emit(str(exc))
            custom_logger.handle_exception(
                exc,
                behavior=custom_logger.LOG_ONLY,
                logger_name=logger.name,
                context="metadata enrichment worker",
                reraise=False,
            )
            self.enrichment_finished.emit()

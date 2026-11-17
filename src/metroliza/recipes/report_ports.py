"""Reports recipe ports sharing the existing preflight and approved import plan.

The injected executors own execution and cooperative cancellation. This module
never starts Qt, opens a widget, or writes the destination during review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from threading import Event
from typing import Callable
from uuid import uuid4

from metroliza.recipes.export_service import ExportRecipeService
from metroliza.exporting.output_publication import conflicting_outputs
from metroliza.parsing.metadata_review import MetadataReviewReader, MODE_FAST, MODE_OCR, READING_OK
from metroliza.parsing.preflight import (
    MAX_IMPORT_REVIEWED_OCR_BYTES, ImportPlan, ParsePreflightService, ParsePreflightStatus,
    ReviewedReportOcr, SelectedReportIdentity,
)
from metroliza.recipes.contracts import ParameterKey, RecipeError, ResolvedRunPlan, StepKind
from metroliza.recipes.ports import PreparationPhase, PreflightResult, ResultCode, StepContext, StepResult, StepStatus
from metroliza.reports.report_metadata_review import ReviewRow, build_overrides
from metroliza.reports.db import sqlite_file_identity, sqlite_readonly_connection_scope
from metroliza.reports.report_schema import is_report_schema_ready
from metroliza.shared.parse_contracts import ParseRequest


@dataclass(frozen=True)
class ImportExecutionResult:
    imported: int = 0
    duplicates: int = 0
    failed: int = 0
    changed: int = 0
    cancelled: bool = False
    enrichment_complete: bool = True
    cleanup_complete: bool = True
    accepted_occurrences: tuple[str, ...] = field(default=(), repr=False)


@dataclass(repr=False)
class ReportReview:
    request: ParseRequest
    preflight: object
    rows: tuple[ReviewRow, ...]
    conflicts: tuple
    decision_id: str = field(default_factory=lambda: str(uuid4()))
    approved: bool = False
    consents: tuple = ()
    import_plan: ImportPlan | None = None
    imported: bool = False
    database_identity: tuple[int, int] | None = None
    reviewed_ocr: tuple[ReviewedReportOcr, ...] = ()
    retained_digests: tuple[str, ...] = ()
    export_digests: tuple[str, ...] = ()


class ReportsRecipeService:
    def __init__(self, import_executor: Callable, export_executor: Callable, *, scanner=None,
                 metadata_reader=MetadataReviewReader):
        self.import_executor = import_executor
        self.export_service = ExportRecipeService(export_executor)
        self.scanner = scanner or ParsePreflightService()
        self.metadata_reader = metadata_reader
        self._reviews: dict[str, ReportReview] = {}
        self._cancelled = Event()

    def finish(self, plan) -> None:
        review = self._reviews.pop(plan.run_id, None)
        if review is not None:
            review.reviewed_ocr = ()
            review.import_plan = None

    @staticmethod
    def _output_targets(plan):
        targets = [plan.output_file]
        if any(s.kind is StepKind.EXPORT_HTML for s in plan.definition.steps):
            targets.append(plan.output_file.with_suffix(".html"))
        return tuple(dict.fromkeys(p for p in targets if p is not None))

    def cancel(self) -> None:
        self._cancelled.set()
        for executor in (self.import_executor, self.export_service.executor):
            cancel = getattr(executor, "cancel", None)
            if cancel is not None:
                cancel()

    def _scan(self, request, context, *, preserve_existing=False):
        context.set_phase(PreparationPhase.SCAN)
        return self.scanner.scan_source(
            source_path=request.source_directory, database_path=request.db_file,
            metadata_parsing_mode=request.metadata_parsing_mode,
            should_cancel=lambda: self._cancelled.is_set() or context.cancelled(),
            on_progress=lambda done, total, _name: context.progress(done, total),
            **({"preserve_existing": True} if preserve_existing else {}),
        )

    def preflight(self, plan: ResolvedRunPlan, context: StepContext) -> PreflightResult:
        self._cancelled.clear()
        from metroliza.recipes.report_configuration_adapter import validate_report_configuration
        validate_report_configuration(plan)
        if plan.database_file is None or plan.output_file is None:
            return PreflightResult(False, ResultCode.INVALID_PLAN)
        if not any(s.kind is StepKind.IMPORT_REPORTS for s in plan.definition.steps):
            return self._preflight_existing_database(plan)
        if plan.input_folder is None:
            return PreflightResult(False, ResultCode.INVALID_PLAN)
        return self._preflight_import(plan, context)

    def _preflight_existing_database(self, plan):
        try:
            with sqlite_readonly_connection_scope(str(plan.database_file)) as connection:
                if not is_report_schema_ready(connection):
                    return PreflightResult(False, ResultCode.INVALID_PLAN)
        except sqlite3.Error:
            return PreflightResult(False, ResultCode.INVALID_PLAN)
        previous = self._reviews.get(plan.run_id)
        if previous is not None and previous.approved:
            return PreflightResult(True)
        conflicts = conflicting_outputs(self._output_targets(plan))
        review = ReportReview(ParseRequest("", str(plan.database_file)), None, (), conflicts,
                              imported=True, approved=not bool(conflicts),
                              consents=self.export_service.replacement_consents(conflicts))
        self._reviews[plan.run_id] = review
        return PreflightResult(not bool(conflicts),
            ResultCode.REVIEW_REQUIRED if conflicts else ResultCode.SUCCESS, bool(conflicts),
            review.decision_id, (f"Wyniki wymagające zgody na zastąpienie: {len(conflicts)}",), review)

    def _preflight_import(self, plan, context):
        identity = None
        if plan.appends_to_database:
            identity = sqlite_file_identity(plan.database_file)
            if identity is None or not self._database_is_current(plan.database_file, identity):
                return PreflightResult(False, ResultCode.DATABASE_UNAVAILABLE)
        mode = str(plan.value(ParameterKey.METADATA_MODE, MODE_OCR))
        request = ParseRequest(str(plan.input_folder), str(plan.database_file), mode)
        scan = self._scan(request, context, preserve_existing=plan.appends_to_database)
        if scan.cancelled or context.cancelled():
            return PreflightResult(False, ResultCode.CANCELLED)
        previous = self._reviews.get(plan.run_id)
        if previous is not None and previous.approved:
            if previous.preflight.result_id != scan.result_id or previous.request != request:
                self._reviews.pop(plan.run_id, None)
                return PreflightResult(False, ResultCode.SOURCE_CHANGED)
            return PreflightResult(True)
        rows, reviewed_ocr = self._read_review_rows(scan, mode, context)
        if context.cancelled() or self._cancelled.is_set():
            return PreflightResult(False, ResultCode.CANCELLED)
        return self._review_preflight(plan, request, scan, rows, reviewed_ocr, identity)

    def _read_review_rows(self, scan, mode, context):
        context.set_phase(PreparationPhase.METADATA if mode == MODE_FAST else PreparationPhase.OCR)
        ready = {item.stable_occurrence_id: item for item in scan.ready_files}
        rows = tuple(ReviewRow(key, item.fingerprint or "", item.display_name, item.parser_id)
                     for key, item in ready.items())
        by_id = {row.occurrence_id: row for row in rows}
        reviewed_ocr = []
        remaining = MAX_IMPORT_REVIEWED_OCR_BYTES

        def on_reading(reading):
            nonlocal remaining
            row = by_id[reading.occurrence_id]
            if reading.status == READING_OK and reading.selection is not None:
                row.apply_fast(reading.selection)
                header = getattr(reading, "header_ocr", None)
                item = ready[row.occurrence_id]
                if header is not None and len(header.payload) <= remaining and item.registry_generation_id is not None:
                    identity = SelectedReportIdentity(row.occurrence_id, row.fingerprint,
                                                      item.parser_id or "", item.registry_generation_id)
                    reviewed_ocr.append(ReviewedReportOcr(identity, header))
                    remaining -= len(header.payload)
            else:
                row.mark_failed(reading.note, state=reading.status)

        self.metadata_reader(scan).read(
            by_id, mode=mode, should_cancel=lambda: context.cancelled() or self._cancelled.is_set(),
            on_reading=on_reading,
            on_progress=lambda done, total, _name: context.progress(done, total),
        )
        return rows, tuple(reviewed_ocr)

    def _review_preflight(self, plan, request, scan, rows, reviewed_ocr, identity):
        conflicts = conflicting_outputs(self._output_targets(plan))
        retained = () if identity is None else tuple(dict.fromkeys(
            item.fingerprint.removeprefix("sha256:") for item in scan.files
            if item.status is ParsePreflightStatus.DUPLICATE and item.fingerprint
            and "duplicate_in_selected_source" not in item.reason_codes
        ))
        review = ReportReview(request, scan, rows, conflicts,
                              consents=self.export_service.replacement_consents(conflicts),
                              database_identity=identity, reviewed_ocr=reviewed_ocr, retained_digests=retained)
        self._reviews[plan.run_id] = review
        issues = any(item.status not in (ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE)
                     for item in scan.files)
        attention = any(row.needs_attention or row.conflict_fields or row.warnings for row in rows)
        summary = (f"Raporty do importu: {len(rows)}",
                   f"Rozpoznane duplikaty: {scan.count(ParsePreflightStatus.DUPLICATE)}",
                   f"Wyniki wymagające zgody na zastąpienie: {len(conflicts)}")
        if not (rows or retained) or issues or attention or conflicts:
            return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True,
                                   review.decision_id, summary, review,
                                   recheck_on_continue=plan.definition.steps[0].kind not in {
                                       StepKind.PREPARE_DATABASE, StepKind.PREPARE_EXISTING_DATABASE,
                                   })
        # Start approves only this complete, unambiguous current review.
        review.import_plan = self._build_import_plan(review)
        review.approved = True
        return PreflightResult(True, summary=summary, review=review)

    def approve(self, plan: ResolvedRunPlan, decision: str) -> bool:
        review = self._reviews.get(plan.run_id)
        if review is None or decision not in ("continue", "continue_partial"):
            return False
        if review.preflight is None:
            review.approved = True
            return True
        if not (review.rows or review.retained_digests) or any(
            row.state in ("changed", "failed", "pending") for row in review.rows
        ):
            return False
        # Explicit review may accept missing metadata; user edits are carried by the same plan.
        review.import_plan = self._build_import_plan(review, user_reviewed=True)
        review.approved = True
        return True

    @staticmethod
    def _build_import_plan(review, *, user_reviewed=False):
        return ImportPlan.from_preflight(
            review.request, review.preflight,
            selected_occurrence_ids=(row.occurrence_id for row in review.rows),
            metadata_overrides=build_overrides(review.rows) if user_reviewed else (),
            reviewed_ocr=review.reviewed_ocr,
            existing_database_identity=review.database_identity,
        )

    def execute(self, step, plan: ResolvedRunPlan, context: StepContext) -> StepResult:
        if context.cancelled() or self._cancelled.is_set():
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        review = self._reviews.get(plan.run_id)
        if review is None or not review.approved:
            return StepResult(StepStatus.FAILED, ResultCode.REVIEW_REQUIRED)
        if step.kind in (StepKind.OPEN_DATABASE, StepKind.FILTER, StepKind.GROUP):
            from metroliza.recipes.report_configuration_adapter import validate_report_configuration
            validate_report_configuration(plan)
            return StepResult(StepStatus.COMPLETED)
        if step.kind in {StepKind.PREPARE_DATABASE, StepKind.PREPARE_EXISTING_DATABASE}:
            return self._verify_import_source(review, context)
        if step.kind is StepKind.IMPORT_REPORTS:
            return self._import_reports(review, context)
        if step.kind in (StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML):
            return self._export(step, plan, review, context)
        if step.kind is StepKind.VERIFY_OUTPUT:
            return self._verify_outputs(plan, review)
        return StepResult(StepStatus.FAILED, ResultCode.UNSUPPORTED)

    def _verify_import_source(self, review, context):
        # The importer owns schema creation inside its approved connection.
        existing = review.database_identity is not None
        if existing and not self._database_is_current(review.request.db_file, review.database_identity):
            return StepResult(StepStatus.FAILED, ResultCode.DATABASE_UNAVAILABLE)
        current = self._scan(review.request, context, preserve_existing=existing)
        if current.cancelled:
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        if current.result_id != review.preflight.result_id:
            return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED)
        if existing and sqlite_file_identity(review.request.db_file) != review.database_identity:
            return StepResult(StepStatus.FAILED, ResultCode.DATABASE_UNAVAILABLE)
        return StepResult(StepStatus.COMPLETED)

    def _import_reports(self, review, context):
        if review.import_plan is None:
            return StepResult(StepStatus.FAILED, ResultCode.REVIEW_REQUIRED)
        result = (self.import_executor(review.import_plan, context) if review.import_plan.selected_reports
                  else ImportExecutionResult())
        failure = self._import_failure(result)
        if failure is not None:
            return failure
        return self._record_import(review, result)

    @staticmethod
    def _import_failure(result):
        if not result.cleanup_complete:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED, result.imported, result.failed)
        if result.cancelled:
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED, result.imported, result.failed)
        if not result.enrichment_complete:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED, result.imported, result.failed)
        if result.changed:
            return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED, result.imported, result.changed)
        return None

    def _record_import(self, review, result):
        existing = review.import_plan.existing_database_identity
        duplicate_count = result.duplicates + len(review.retained_digests)
        if existing is not None:
            if sqlite_file_identity(review.request.db_file) != existing:
                return StepResult(StepStatus.FAILED, ResultCode.DATABASE_UNAVAILABLE, result.imported, result.failed)
            if not self._bind_append_export_scope(review, result):
                return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED, result.imported, result.failed)
        review.imported = result.imported + duplicate_count > 0
        if review.imported and existing is None:
            review.database_identity = sqlite_file_identity(review.request.db_file)
        if result.failed:
            return StepResult(StepStatus.PARTIAL if review.imported else StepStatus.FAILED,
                              ResultCode.PARTIAL_IMPORT, result.imported, result.failed, duplicate_count=duplicate_count)
        warnings = []
        if duplicate_count and existing is None:
            warnings.append(ResultCode.DUPLICATES)
        if any(item.status not in (ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE)
               for item in review.preflight.files):
            warnings.append(ResultCode.UNSUPPORTED)
        return StepResult(StepStatus.COMPLETED, imported_count=result.imported, warnings=tuple(warnings),
                          duplicate_count=duplicate_count)

    @staticmethod
    def _bind_append_export_scope(review, result):
        accepted = set(result.accepted_occurrences)
        digests = tuple(item.fingerprint.removeprefix("sha256:") for item in review.import_plan.selected_reports
                        if item.occurrence_id in accepted)
        if len(digests) != result.imported + result.duplicates:
            return False
        review.export_digests = tuple(dict.fromkeys((*review.retained_digests, *digests)))
        return True

    @staticmethod
    def _database_is_current(path, identity):
        try:
            with sqlite_readonly_connection_scope(str(path), existing_identity=identity):
                return True
        except (OSError, sqlite3.Error):
            return False

    def _verify_imported_database(self, plan, review) -> bool:
        if not (plan.creates_database or plan.appends_to_database):
            return True  # Existing-DB export consumes an input, not a newly owned DB.
        path = plan.database_file
        if path is None or review.database_identity is None:
            return False
        if sqlite_file_identity(path) != review.database_identity:
            return False
        try:
            # Bounded structural sanity: no full-table integrity scan, migration,
            # measurement reprocessing or source rescan at flow completion.
            with sqlite_readonly_connection_scope(str(path)) as connection:
                if not is_report_schema_ready(connection):
                    return False
                connection.execute("SELECT id FROM parsed_reports LIMIT 1").fetchone()
                connection.execute("SELECT report_id FROM report_measurements LIMIT 1").fetchone()
        except (OSError, sqlite3.Error):
            return False
        return sqlite_file_identity(path) == review.database_identity

    def _verify_outputs(self, plan, review) -> StepResult:
        verified = self._verify_imported_database(plan, review) and all(
            self.export_service.verify(path) for path in self._output_targets(plan))
        return StepResult(StepStatus.COMPLETED if verified else StepStatus.FAILED,
                          ResultCode.SUCCESS if verified else ResultCode.OUTPUT_MISSING,
                          artifact_verified=verified)

    def _export(self, step, plan, review, context):
        if not review.imported:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED)
        try:
            return self.export_service.execute(
                plan, context, consents=review.consents, step_kind=step.kind,
                source_digests=review.export_digests,
                existing_identity=review.database_identity if plan.appends_to_database else None,
            )
        except (sqlite3.Error, OSError, RecipeError):
            if plan.appends_to_database:
                return StepResult(StepStatus.FAILED, ResultCode.DATABASE_UNAVAILABLE)
            raise

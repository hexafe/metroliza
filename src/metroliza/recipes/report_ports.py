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
from metroliza.parsing.metadata_review import MetadataReviewReader, MODE_OCR, READING_OK
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService, ParsePreflightStatus
from metroliza.recipes.contracts import ResolvedRunPlan, StepKind
from metroliza.recipes.ports import PreflightResult, ResultCode, StepContext, StepResult, StepStatus
from metroliza.reports.report_metadata_review import ReviewRow, build_overrides
from metroliza.reports.db import sqlite_readonly_connection_scope
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
        self._reviews.pop(plan.run_id, None)

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

    def _scan(self, request, context):
        return self.scanner.scan_source(
            source_path=request.source_directory, database_path=request.db_file,
            metadata_parsing_mode=request.metadata_parsing_mode,
            should_cancel=lambda: self._cancelled.is_set() or context.cancelled(),
            on_progress=lambda done, total, _name: context.progress(done, total),
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
                              imported=True, approved=not bool(conflicts))
        self._reviews[plan.run_id] = review
        return PreflightResult(not bool(conflicts),
            ResultCode.REVIEW_REQUIRED if conflicts else ResultCode.SUCCESS, bool(conflicts),
            review.decision_id, (f"Outputs requiring replacement consent: {len(conflicts)}",), review)

    def _preflight_import(self, plan, context):
        request = ParseRequest(str(plan.input_folder), str(plan.database_file), "complete", False)
        scan = self._scan(request, context)
        if scan.cancelled or context.cancelled():
            return PreflightResult(False, ResultCode.CANCELLED)
        previous = self._reviews.get(plan.run_id)
        if previous is not None and previous.approved:
            if previous.preflight.result_id != scan.result_id or previous.request != request:
                self._reviews.pop(plan.run_id, None)
                return PreflightResult(False, ResultCode.SOURCE_CHANGED)
            return PreflightResult(True)
        rows = self._read_review_rows(scan, context)
        if context.cancelled() or self._cancelled.is_set():
            return PreflightResult(False, ResultCode.CANCELLED)
        return self._review_preflight(plan, request, scan, rows)

    def _read_review_rows(self, scan, context):
        rows = tuple(ReviewRow(item.stable_occurrence_id, item.fingerprint or "",
                               item.display_name, item.parser_id) for item in scan.ready_files)
        by_id = {row.occurrence_id: row for row in rows}

        def on_reading(reading):
            row = by_id[reading.occurrence_id]
            if reading.status == READING_OK and reading.selection is not None:
                row.apply_fast(reading.selection)
            else:
                row.mark_failed(reading.note, state=reading.status)

        self.metadata_reader(scan).read(
            by_id, mode=MODE_OCR, should_cancel=lambda: context.cancelled() or self._cancelled.is_set(),
            on_reading=on_reading,
            on_progress=lambda done, total, _name: context.progress(done, total),
        )
        return rows

    def _review_preflight(self, plan, request, scan, rows):
        conflicts = conflicting_outputs(self._output_targets(plan))
        review = ReportReview(request, scan, rows, conflicts)
        self._reviews[plan.run_id] = review
        issues = any(item.status not in (ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE)
                     for item in scan.files)
        attention = any(row.needs_attention or row.conflict_fields or row.warnings for row in rows)
        summary = (f"Reports ready: {len(rows)}", f"Duplicates: {scan.count(ParsePreflightStatus.DUPLICATE)}",
                   f"Outputs requiring replacement consent: {len(conflicts)}")
        if not rows or issues or attention or conflicts:
            return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True,
                                   review.decision_id, summary, review)
        # Start approves only this complete, unambiguous current review.
        review.import_plan = ImportPlan.from_preflight(
            request, scan, selected_occurrence_ids=(row.occurrence_id for row in rows),
        )
        review.approved = True
        return PreflightResult(True, summary=summary, review=review)

    def approve(self, plan: ResolvedRunPlan, decision: str) -> bool:
        review = self._reviews.get(plan.run_id)
        if review is None or decision not in ("continue", "continue_partial"):
            return False
        if review.preflight is None:
            review.consents = self.export_service.replacement_consents(review.conflicts)
            review.approved = True
            return True
        if not review.rows or any(row.state in ("changed", "failed", "pending") for row in review.rows):
            return False
        # Explicit review may accept missing metadata; user edits are carried by the same plan.
        review.import_plan = ImportPlan.from_preflight(
            review.request, review.preflight,
            selected_occurrence_ids=(row.occurrence_id for row in review.rows),
            metadata_overrides=build_overrides(review.rows),
        )
        review.consents = self.export_service.replacement_consents(review.conflicts)
        review.approved = True
        return True

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
        if step.kind is StepKind.PREPARE_DATABASE:
            return self._verify_import_source(review, context)
        if step.kind is StepKind.IMPORT_REPORTS:
            return self._import_reports(review, context)
        if step.kind in (StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML):
            return self._export(step, plan, review, context)
        if step.kind is StepKind.VERIFY_OUTPUT:
            verified = all(self.export_service.verify(p) for p in self._output_targets(plan))
            return StepResult(StepStatus.COMPLETED if verified else StepStatus.FAILED,
                              ResultCode.SUCCESS if verified else ResultCode.OUTPUT_MISSING,
                              artifact_verified=verified)
        return StepResult(StepStatus.FAILED, ResultCode.UNSUPPORTED)

    def _verify_import_source(self, review, context):
        # The importer owns schema creation inside its approved connection.
        current = self._scan(review.request, context)
        if current.cancelled:
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        if current.result_id != review.preflight.result_id:
            return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED)
        return StepResult(StepStatus.COMPLETED)

    def _import_reports(self, review, context):
        if review.import_plan is None:
            return StepResult(StepStatus.FAILED, ResultCode.REVIEW_REQUIRED)
        result = self.import_executor(review.import_plan, context)
        if not result.cleanup_complete:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED, result.imported, result.failed)
        if result.cancelled:
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED, result.imported, result.failed)
        if not result.enrichment_complete:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED, result.imported, result.failed)
        if result.changed:
            return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED, result.imported, result.changed)
        review.imported = result.imported + result.duplicates > 0
        if result.failed:
            return StepResult(StepStatus.PARTIAL if review.imported else StepStatus.FAILED,
                              ResultCode.PARTIAL_IMPORT, result.imported, result.failed)
        warnings = []
        if result.duplicates:
            warnings.append(ResultCode.DUPLICATES)
        if any(item.status not in (ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE)
               for item in review.preflight.files):
            warnings.append(ResultCode.UNSUPPORTED)
        return StepResult(StepStatus.COMPLETED, imported_count=result.imported, warnings=tuple(warnings))

    def _export(self, step, plan, review, context):
        if not review.imported:
            return StepResult(StepStatus.FAILED, ResultCode.IMPORT_FAILED)
        return self.export_service.execute(plan, context, consents=review.consents, step_kind=step.kind)

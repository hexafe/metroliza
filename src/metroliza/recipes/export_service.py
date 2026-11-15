"""Request construction and artifact verification for recipe exports, without Qt."""
from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile
from typing import Callable

from metroliza.exporting.export_outcomes import ExportRunStatus
from metroliza.exporting.output_publication import OutputConsent
from metroliza.recipes.contracts import ResolvedRunPlan, StepKind
from metroliza.recipes.ports import ResultCode, StepContext, StepResult, StepStatus


class ExportRecipeService:
    def __init__(self, executor: Callable):
        self.executor = executor

    def execute(self, plan: ResolvedRunPlan, context: StepContext, *, consents=(), step_kind=StepKind.EXPORT_MAIN) -> StepResult:
        from metroliza.recipes.report_configuration_adapter import build_export_request

        if plan.database_file is None or plan.output_file is None:
            return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)
        request = build_export_request(plan, step_kind, consents=consents)
        result = self.executor(request, context)
        if result.status is ExportRunStatus.CANCELLED:
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        if result.status is ExportRunStatus.FAILED:
            return StepResult(StepStatus.FAILED, ResultCode.EXPORT_FAILED)
        if not self.verify(Path(request.paths.html_dashboard_file or request.paths.excel_file)):
            return StepResult(StepStatus.FAILED, ResultCode.OUTPUT_MISSING)
        partial = result.status is ExportRunStatus.COMPLETE_WITH_OMISSIONS
        return StepResult(
            StepStatus.PARTIAL if partial else StepStatus.COMPLETED,
            ResultCode.EXPORT_FAILED if partial else ResultCode.SUCCESS,
            artifact_verified=True,
        )

    @staticmethod
    def verify(path: Path | None) -> bool:
        try:
            if path is None or not path.is_file() or path.stat().st_size <= 0:
                return False
            if path.suffix.lower() == ".xlsx":
                from zipfile import ZipFile
                with ZipFile(path) as archive:
                    required = {"[Content_Types].xml", "xl/workbook.xml"}
                    return required.issubset(archive.namelist()) and archive.testzip() is None
            if path.suffix.lower() == ".html":
                with path.open("r", encoding="utf-8") as stream:
                    opening = stream.read(65536).lower()
                return "<html" in opening and ("dashboard" in opening or "<!doctype html" in opening)
            return False
        except (OSError, ValueError, UnicodeError, BadZipFile):
            return False

    @staticmethod
    def replacement_consents(paths) -> tuple[OutputConsent, ...]:
        return tuple(OutputConsent.for_path(path) for path in paths if Path(path).exists())

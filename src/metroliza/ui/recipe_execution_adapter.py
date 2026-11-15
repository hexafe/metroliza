"""Presentation adapter sharing the manual Reports workers synchronously.

Only this boundary depends on Qt. Workers run on the controller's single owned
thread; their existing run/finally paths retain schema, publication and cleanup.
"""
from __future__ import annotations

from threading import Event, Lock
from uuid import UUID

from PyQt6.QtCore import Qt

from metroliza.exporting.export_data_thread import ExportDataThread
from metroliza.exporting.export_outcomes import derive_export_run_result
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.recipes.report_ports import ImportExecutionResult
from metroliza.shared.workflow_diagnostics import recipe_workflow_scope


class RecipeExecutionAdapter:
    def __init__(self, kind: str):
        if kind not in ("import", "export"):
            raise ValueError("unsupported_recipe_execution_kind")
        self.kind = kind
        self._active = None
        self._lock = Lock()
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()
        with self._lock:
            worker = self._active
            if worker is not None:
                self._stop(worker)

    def _stop(self, worker):
        if self.kind == "import":
            worker.stop_parsing()
        else:
            worker.stop_exporting()

    def __call__(self, request, context):
        self._cancel.clear()
        worker = ParseReportsThread(request) if self.kind == "import" else ExportDataThread(request)
        errors = []
        worker.error_occurred.connect(lambda _message: errors.append(True), Qt.ConnectionType.DirectConnection)

        def progress(value):
            if context.cancelled() or self._cancel.is_set():
                self._stop(worker)
            context.progress(value, 100)

        worker.update_progress.connect(progress, Qt.ConnectionType.DirectConnection)
        with self._lock:
            self._active = worker
            if context.cancelled() or self._cancel.is_set():
                self._stop(worker)
        try:
            with recipe_workflow_scope(UUID(context.flow_id), UUID(context.run_id), UUID(context.step_id)):
                worker.run()
            if self.kind == "import":
                result = worker.last_parse_result
                enrichment = worker.last_enrichment_result
                complete = enrichment is None or (
                    not enrichment.failed_files and not enrichment.cancelled_files
                    and not enrichment.cancellation_requested
                )
                return ImportExecutionResult(
                    imported=result.imported_files,
                    duplicates=result.already_present_files,
                    failed=max(result.failed_files, int(bool(errors))),
                    changed=result.preflight_changed_files,
                    cancelled=worker.parsing_canceled,
                    enrichment_complete=complete,
                    cleanup_complete=worker._prepare_pool is None,
                )
            return worker.export_run_result or derive_export_run_result(
                excel_file=worker.excel_file, export_target=worker.export_target,
                completion_metadata=worker.completion_metadata,
                cancelled=worker.export_canceled,
                terminal_failure="export_failed" if errors else "export_not_completed",
            )
        finally:
            with self._lock:
                self._active = None
            self._cancel.clear()

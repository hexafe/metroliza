"""Background workers for Oznak industrial sync, link refresh, and cached export."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from modules.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSourceProfile,
    redact_sensitive_text,
)
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from modules.industrial_analytics_workflow import (
    AnalyticsCancelled,
    run_production_cache_analytics,
    run_tabular_file_analytics,
)
from modules.industrial_export_service import (
    IndustrialExportCancelled,
    export_cached_industrial_workbook,
)
from modules.industrial_join_service import materialize_industrial_report_links
from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from modules.oznak_adapter import (
    create_oznak_cancellation_token,
    fetch_oznak_records_for_source_profile,
    get_oznak_adapter_status,
)


class IndustrialLinkRefreshThread(QThread):
    """Run local industrial link refresh outside the Qt main thread."""

    summary_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, db_file: str):
        super().__init__()
        self.db_file = db_file

    def run(self):
        try:
            self.summary_ready.emit(materialize_industrial_report_links(self.db_file))
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class IndustrialExportThread(QThread):
    """Write cached industrial export workbook outside the Qt main thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(
        self,
        *,
        db_file: str,
        output_file: str,
        filter_state: IndustrialFilterState,
        grouping_state: IndustrialGroupingState,
        include_charts: bool,
    ):
        super().__init__()
        self.db_file = db_file
        self.output_file = output_file
        self.filter_state = filter_state
        self.grouping_state = grouping_state
        self.include_charts = include_charts
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def run(self):
        try:
            self.result_ready.emit(
                export_cached_industrial_workbook(
                    db_file=self.db_file,
                    output_file=self.output_file,
                    filter_state=self.filter_state,
                    grouping_state=self.grouping_state,
                    include_charts=self.include_charts,
                    cancel_check=self._is_cancelled,
                )
            )
        except IndustrialExportCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.error_occurred.emit(redact_sensitive_text(exc))


class IndustrialAnalyticsThread(QThread):
    """Create production/file analytics dashboard and workbook outside the Qt main thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    update_label = pyqtSignal(str)

    def __init__(
        self,
        *,
        source_kind: str,
        db_file: str = "",
        input_file: str = "",
        output_dashboard_file: str,
        output_workbook_file: str = "",
        metric_selection: tuple[ProductionMetricSelection, ...] = (),
        filter_state: ProductionFilterState | None = None,
        aggregation_state: ProductionAggregationState | None = None,
        cohort_state: ReferenceCohortState | None = None,
        chart_selection: ProductionChartSelection | None = None,
        separate_parameter_sheets: bool = True,
        sheet_name: str | int | None = None,
        timestamp_column: str | None = None,
        reference_column: str | None = None,
        tabular_filter_columns: tuple[str, ...] | list[str] | None = None,
        tabular_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        grouping_df=None,
    ):
        super().__init__()
        self.source_kind = source_kind
        self.db_file = db_file
        self.input_file = input_file
        self.output_dashboard_file = output_dashboard_file
        self.output_workbook_file = output_workbook_file
        self.metric_selection = tuple(metric_selection or ())
        self.filter_state = filter_state or ProductionFilterState()
        self.aggregation_state = aggregation_state or ProductionAggregationState()
        self.cohort_state = cohort_state or ReferenceCohortState()
        self.chart_selection = chart_selection or ProductionChartSelection()
        self.separate_parameter_sheets = bool(separate_parameter_sheets)
        self.sheet_name = sheet_name
        self.timestamp_column = timestamp_column
        self.reference_column = reference_column
        self.tabular_filter_columns = tuple(tabular_filter_columns or ())
        self.tabular_filter_keys = tuple(tuple(key) for key in (tabular_filter_keys or ()))
        self.grouping_df = grouping_df
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def _emit_progress_message(self, message: str) -> None:
        self.update_label.emit(message)

    def run(self):
        try:
            if self.source_kind == "tabular_file":
                result = run_tabular_file_analytics(
                    input_file=self.input_file,
                    output_dashboard_file=self.output_dashboard_file,
                    output_workbook_file=self.output_workbook_file or None,
                    metric_selection=self.metric_selection,
                    sheet_name=self.sheet_name,
                    timestamp_column=self.timestamp_column,
                    reference_column=self.reference_column,
                    tabular_filter_columns=self.tabular_filter_columns,
                    tabular_filter_keys=self.tabular_filter_keys,
                    grouping_df=self.grouping_df,
                    aggregation_state=self.aggregation_state,
                    cohort_state=self.cohort_state,
                    chart_selection=self.chart_selection,
                    separate_parameter_sheets=self.separate_parameter_sheets,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._emit_progress_message,
                )
            else:
                result = run_production_cache_analytics(
                    db_file=self.db_file,
                    output_dashboard_file=self.output_dashboard_file,
                    output_workbook_file=self.output_workbook_file or None,
                    metric_selection=self.metric_selection,
                    filter_state=self.filter_state,
                    aggregation_state=self.aggregation_state,
                    cohort_state=self.cohort_state,
                    chart_selection=self.chart_selection,
                    separate_parameter_sheets=self.separate_parameter_sheets,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._emit_progress_message,
                )
            self.result_ready.emit(result)
        except AnalyticsCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class IndustrialOznakSyncThread(QThread):
    """Run Oznak connection tests and source sync outside the Qt main thread."""

    progress_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        *,
        db_file: str,
        profile: IndustrialSourceProfile,
        username: str,
        password: str,
        limit: int,
        timeout_seconds: int,
        reference_filter_column: str | None,
        reference_values: tuple[str, ...],
        test_only: bool,
    ):
        super().__init__()
        self.db_file = db_file
        self.profile = profile
        self.username = username
        self.password = password
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.reference_filter_column = reference_filter_column
        self.reference_values = reference_values
        self.test_only = test_only
        self.cancellation_token = None
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        token = self.cancellation_token
        if token is not None and hasattr(token, "cancel"):
            token.cancel()

    def run(self):
        repository = IndustrialDataRepository(self.db_file)
        sync_run_id: int | None = None
        try:
            status = get_oznak_adapter_status()
            if status.available:
                try:
                    self.cancellation_token = create_oznak_cancellation_token()
                except Exception:
                    self.cancellation_token = None
            requested_limit = 1 if self.test_only else self.limit
            if not self.test_only:
                sync_run_id = repository.create_sync_run(
                    source_profile_id=self.profile.id,
                    filters={
                        "limit": requested_limit,
                        "timeout_seconds": self.timeout_seconds,
                        "reference_filter_column": self.reference_filter_column,
                        "reference_count": len(self.reference_values),
                    },
                    oznak_version=status.version,
                    diagnostics={"adapter": status.diagnostics},
                )

            result = fetch_oznak_records_for_source_profile(
                self.profile,
                username=self.username,
                password=self.password,
                limit=requested_limit,
                timeout_seconds=self.timeout_seconds,
                reference_filter_column=self.reference_filter_column,
                reference_values=self.reference_values,
                cancellation_token=self.cancellation_token,
                progress_callback=self._emit_progress_from_diagnostic,
            )

            if self._cancel_requested:
                final_status = "cancelled"
                error = "Sync cancelled by user."
            elif result.error:
                final_status = "failed"
                error = redact_sensitive_text(result.error)
            else:
                final_status = "succeeded"
                error = None

            upsert_summary: dict[str, int] = {}
            link_summary = None
            if not self.test_only and final_status == "succeeded":
                upsert_summary = repository.upsert_industrial_records_from_rows(
                    source_profile_id=self.profile.id,
                    source_db_alias=self.profile.source_db_alias,
                    rows=result.records,
                    sync_run_id=sync_run_id,
                )
                link_summary = materialize_industrial_report_links(self.db_file)

            if sync_run_id is not None:
                repository.finish_sync_run(
                    sync_run_id=sync_run_id,
                    status=final_status,
                    row_count=result.row_count,
                    error_summary=error,
                    diagnostics=result.diagnostics,
                )

            self.result_ready.emit(
                {
                    "test_only": self.test_only,
                    "status": final_status,
                    "error": error,
                    "row_count": result.row_count,
                    "upsert_summary": upsert_summary,
                    "link_summary": link_summary,
                    "diagnostics": result.diagnostics,
                }
            )
        except Exception as exc:
            sanitized_error = redact_sensitive_text(exc)
            if sync_run_id is not None:
                try:
                    repository.finish_sync_run(
                        sync_run_id=sync_run_id,
                        status="cancelled" if self._cancel_requested else "failed",
                        row_count=0,
                        error_summary=sanitized_error,
                        diagnostics={"stage": "thread_error"},
                    )
                except Exception:
                    pass
            self.error_occurred.emit(sanitized_error)

    def _emit_progress_from_diagnostic(self, diagnostic: Any) -> None:
        message = getattr(diagnostic, "message", None)
        if not message:
            source = getattr(diagnostic, "source_alias", "")
            status = getattr(getattr(diagnostic, "status", None), "value", None) or getattr(
                diagnostic, "status", ""
            )
            message = f"{source}: {status}".strip(": ")
        self.progress_message.emit(str(message))

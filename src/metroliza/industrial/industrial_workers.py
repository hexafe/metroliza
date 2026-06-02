"""Background workers for Oznak industrial sync, link refresh, and cached export."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.shared.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSourceProfile,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from metroliza.industrial.industrial_analytics_workflow import (
    AnalyticsCancelled,
    run_production_cache_analytics,
    run_tabular_file_analytics,
)
from metroliza.tabular.tabular_analytics_service import (
    TabularAnalyticsLoadResult,
    TabularColumnFilter,
    TabularLoadCancelled,
    load_tabular_analytics_file,
    load_tabular_analytics_files,
)
from metroliza.industrial.industrial_export_service import (
    IndustrialExportCancelled,
    export_cached_industrial_workbook,
    export_live_industrial_workbook,
)
from metroliza.industrial.industrial_join_service import materialize_industrial_report_links
from metroliza.industrial.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from metroliza.industrial.oznak_adapter import (
    create_oznak_cancellation_token,
    fetch_oznak_records_for_source_profile,
    get_oznak_adapter_status,
)
from metroliza.shared.worker_cancellation import WorkerCancellationMixin


def _oznak_warning_detail(diagnostics: dict[str, Any]) -> str | None:
    """Return a sanitized short warning detail from Oznak diagnostics."""
    if not isinstance(diagnostics, dict):
        return None
    candidates: list[Any] = []
    candidates.extend(diagnostics.get("errors") or ())
    candidates.extend(diagnostics.get("warnings") or ())
    if diagnostics.get("partial_success") or diagnostics.get("completed_with_warnings"):
        candidates.append("Oznak completed with warnings. Check sync diagnostics for details.")
    for candidate in candidates:
        text = redact_sensitive_text(candidate)
        if text:
            return text
    return None


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


class IndustrialExportThread(WorkerCancellationMixin, QThread):
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
        self._init_cancellation_state()

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


class IndustrialLiveExportThread(WorkerCancellationMixin, QThread):
    """Fetch live Oznak rows and write an industrial workbook outside the Qt main thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    update_label = pyqtSignal(str)

    def __init__(
        self,
        *,
        profile: IndustrialSourceProfile,
        username: str,
        password: str,
        output_file: str,
        limit: int,
        timeout_seconds: int,
        filter_state: IndustrialFilterState,
        grouping_state: IndustrialGroupingState,
        include_charts: bool,
    ):
        super().__init__()
        self.profile = profile
        self.username = username
        self.password = password
        self.output_file = output_file
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.filter_state = filter_state
        self.grouping_state = grouping_state
        self.include_charts = include_charts
        self.cancellation_token = None
        self._init_cancellation_state()

    def _emit_progress_from_diagnostic(self, diagnostic: Any) -> None:
        message = getattr(diagnostic, "message", None)
        if not message:
            source = getattr(diagnostic, "source_alias", "")
            status = getattr(getattr(diagnostic, "status", None), "value", None) or getattr(
                diagnostic,
                "status",
                "",
            )
            message = f"{source}: {status}".strip(": ")
        self.update_label.emit(str(message))

    def run(self):
        try:
            status = get_oznak_adapter_status()
            if status.available:
                try:
                    self.cancellation_token = create_oznak_cancellation_token()
                except Exception:
                    self.cancellation_token = None
            self.result_ready.emit(
                export_live_industrial_workbook(
                    profile=self.profile,
                    username=self.username,
                    password=self.password,
                    output_file=self.output_file,
                    limit=self.limit,
                    timeout_seconds=self.timeout_seconds,
                    filter_state=self.filter_state,
                    grouping_state=self.grouping_state,
                    include_charts=self.include_charts,
                    cancellation_token=self.cancellation_token,
                    progress_callback=self._emit_progress_from_diagnostic,
                    cancel_check=self._is_cancelled,
                )
            )
        except IndustrialExportCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            if self._is_cancelled():
                self.cancelled.emit("Live industrial export was cancelled.")
            else:
                self.error_occurred.emit(redact_sensitive_text(exc))


class IndustrialAnalyticsThread(WorkerCancellationMixin, QThread):
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
        tabular_load_result: TabularAnalyticsLoadResult | None = None,
        tabular_filter_columns: tuple[str, ...] | list[str] | None = None,
        tabular_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        tabular_column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
        dashboard_detail_mode: str = "full",
        grouping_df=None,
        dashboard_visual_settings: dict | None = None,
        dashboard_interactivity_options: object | None = None,
    ):
        super().__init__()
        validated_request = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind=source_kind,
                db_file=db_file,
                input_file=input_file,
                output_dashboard_file=output_dashboard_file,
                output_workbook_file=output_workbook_file,
                metric_selection=tuple(metric_selection or ()),
                filter_state=filter_state,
                aggregation_state=aggregation_state,
                cohort_state=cohort_state,
                chart_selection=chart_selection,
                separate_parameter_sheets=separate_parameter_sheets,
                sheet_name=sheet_name,
                timestamp_column=timestamp_column,
                reference_column=reference_column,
                tabular_load_result=tabular_load_result,
                tabular_filter_columns=tabular_filter_columns or (),
                tabular_filter_keys=tabular_filter_keys or (),
                tabular_column_filters=tabular_column_filters or (),
                dashboard_detail_mode=dashboard_detail_mode,
                grouping_df=grouping_df,
                dashboard_visual_settings=dashboard_visual_settings,
                dashboard_interactivity_options=dashboard_interactivity_options,
            )
        )
        self.request = validated_request
        self.source_kind = validated_request.source_kind
        self.db_file = validated_request.db_file
        self.input_file = validated_request.input_file
        self.output_dashboard_file = validated_request.output_dashboard_file
        self.output_workbook_file = validated_request.output_workbook_file
        self.metric_selection = validated_request.metric_selection
        self.filter_state = validated_request.filter_state or ProductionFilterState()
        self.aggregation_state = validated_request.aggregation_state or ProductionAggregationState()
        self.cohort_state = validated_request.cohort_state or ReferenceCohortState()
        self.chart_selection = validated_request.chart_selection or ProductionChartSelection()
        self.separate_parameter_sheets = validated_request.separate_parameter_sheets
        self.sheet_name = validated_request.sheet_name
        self.timestamp_column = validated_request.timestamp_column
        self.reference_column = validated_request.reference_column
        self.tabular_load_result = validated_request.tabular_load_result
        self.tabular_filter_columns = validated_request.tabular_filter_columns
        self.tabular_filter_keys = validated_request.tabular_filter_keys
        self.tabular_column_filters = validated_request.tabular_column_filters
        self.dashboard_detail_mode = validated_request.dashboard_detail_mode
        self.grouping_df = validated_request.grouping_df
        self.dashboard_visual_settings = validated_request.dashboard_visual_settings
        self.dashboard_interactivity_options = validated_request.dashboard_interactivity_options
        self._init_cancellation_state()

    def _emit_progress_message(self, message: str) -> None:
        self.update_label.emit(message)

    def run(self):
        try:
            if self.source_kind == "tabular_file":
                result = run_tabular_file_analytics(
                    input_file=self.input_file,
                    output_dashboard_file=self.output_dashboard_file,
                    output_workbook_file=self.output_workbook_file or None,
                    tabular_load_result=self.tabular_load_result,
                    metric_selection=self.metric_selection,
                    sheet_name=self.sheet_name,
                    timestamp_column=self.timestamp_column,
                    reference_column=self.reference_column,
                    tabular_filter_columns=self.tabular_filter_columns,
                    tabular_filter_keys=self.tabular_filter_keys,
                    tabular_column_filters=self.tabular_column_filters,
                    dashboard_detail_mode=self.dashboard_detail_mode,
                    grouping_df=self.grouping_df,
                    aggregation_state=self.aggregation_state,
                    cohort_state=self.cohort_state,
                    chart_selection=self.chart_selection,
                    separate_parameter_sheets=self.separate_parameter_sheets,
                    dashboard_visual_settings=self.dashboard_visual_settings,
                    dashboard_interactivity_options=self.dashboard_interactivity_options,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._emit_progress_message,
                )
            elif self.source_kind == "production_cache":
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
                    dashboard_visual_settings=self.dashboard_visual_settings,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._emit_progress_message,
                )
            else:
                raise ValueError(f"Unsupported analytics source kind: {self.source_kind}")
            self.result_ready.emit(result)
        except AnalyticsCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class TabularAnalyticsLoadThread(WorkerCancellationMixin, QThread):
    """Load CSV/Excel analytics rows and metric candidates outside the Qt main thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    update_label = pyqtSignal(str)

    def __init__(
        self,
        *,
        input_file: str,
        input_files: tuple[str, ...] | list[str] | None = None,
        sheet_name: str | int | None = None,
        timestamp_column: str | None = None,
        reference_column: str | None = None,
    ):
        super().__init__()
        self.input_file = input_file
        self.input_files = tuple(input_files or ())
        self.sheet_name = sheet_name
        self.timestamp_column = timestamp_column
        self.reference_column = reference_column
        self._init_cancellation_state()

    def _emit_tabular_load_progress(self, payload: dict[str, Any]) -> None:
        stage = str(payload.get("stage") or "").strip()
        rows_loaded = payload.get("rows_loaded")
        file_name = str(payload.get("file_name") or "").strip()
        file_index = payload.get("file_index")
        file_count = payload.get("file_count")
        stage_labels = {
            "sampling": "Inspecting CSV/Excel data...",
            "loading_file": "Loading CSV/Excel data...",
            "chunk_loaded": "Loading CSV/Excel data...",
            "indexing": "Indexing loaded rows...",
            "preview": "Preparing preview...",
            "complete": "CSV/Excel loading complete",
        }
        detail_parts: list[str] = []
        if file_name:
            detail_parts.append(file_name)
        if file_index is not None and file_count is not None:
            detail_parts.append(f"file {int(file_index)} of {int(file_count)}")
        if rows_loaded is not None:
            detail_parts.append(f"{int(rows_loaded):,} rows loaded")
        detail = " | ".join(detail_parts) if detail_parts else "Reading rows and detecting metrics"
        self.update_label.emit(f"{stage_labels.get(stage, 'Loading CSV/Excel data...')}\n{detail}\nETA --")

    def run(self):
        try:
            self.update_label.emit("Loading CSV/Excel data...\nReading rows and detecting metrics\nETA --")
            if self.input_files:
                result = load_tabular_analytics_files(
                    self.input_files,
                    sheet_name=self.sheet_name,
                    timestamp_column=self.timestamp_column,
                    reference_column=self.reference_column,
                    progress_callback=self._emit_tabular_load_progress,
                    cancel_check=self._is_cancelled,
                )
            else:
                result = load_tabular_analytics_file(
                    self.input_file,
                    sheet_name=self.sheet_name,
                    timestamp_column=self.timestamp_column,
                    reference_column=self.reference_column,
                    progress_callback=self._emit_tabular_load_progress,
                    cancel_check=self._is_cancelled,
                )
            if self._is_cancelled():
                self.cancelled.emit("CSV/Excel loading was canceled.")
                return
            self.result_ready.emit(result)
        except TabularLoadCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            if self._is_cancelled():
                self.cancelled.emit("CSV/Excel loading was canceled.")
            else:
                self.error_occurred.emit(str(exc))


class IndustrialOznakSyncThread(WorkerCancellationMixin, QThread):
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
        self._init_cancellation_state()

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
                        "order_by_enabled": self.profile.order_by_enabled,
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

            warning_detail = _oznak_warning_detail(result.diagnostics)
            if self._cancel_requested:
                final_status = "cancelled"
                error = "Sync cancelled by user."
            elif result.error and not result.records:
                final_status = "failed"
                error = redact_sensitive_text(result.error)
            elif warning_detail or result.error:
                final_status = "completed_with_warnings"
                error = warning_detail or redact_sensitive_text(result.error)
            else:
                final_status = "succeeded"
                error = None

            upsert_summary: dict[str, int] = {}
            link_summary = None
            if not self.test_only and final_status in {"succeeded", "completed_with_warnings"}:
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
                    "access_check_method": "bounded_fetch" if self.test_only else None,
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


class IndustrialOznakAccessCheckThread(WorkerCancellationMixin, QThread):
    """Run a bounded one-row Oznak access check without local cache dependencies."""

    progress_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        *,
        profile: IndustrialSourceProfile,
        username: str,
        password: str,
        timeout_seconds: int,
        reference_filter_column: str | None = None,
        reference_values: tuple[str, ...] = (),
    ):
        super().__init__()
        self.profile = profile
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.reference_filter_column = reference_filter_column
        self.reference_values = reference_values
        self.cancellation_token = None
        self._init_cancellation_state()

    def run(self):
        try:
            status = get_oznak_adapter_status()
            if status.available:
                try:
                    self.cancellation_token = create_oznak_cancellation_token()
                except Exception:
                    self.cancellation_token = None
            result = fetch_oznak_records_for_source_profile(
                self.profile,
                username=self.username,
                password=self.password,
                limit=1,
                timeout_seconds=self.timeout_seconds,
                reference_filter_column=self.reference_filter_column,
                reference_values=self.reference_values,
                cancellation_token=self.cancellation_token,
                progress_callback=self._emit_progress_from_diagnostic,
            )

            warning_detail = _oznak_warning_detail(result.diagnostics)
            if self._cancel_requested:
                final_status = "cancelled"
                error = "Access check cancelled by user."
            elif result.error and not result.records:
                final_status = "failed"
                error = redact_sensitive_text(result.error)
            elif warning_detail or result.error:
                final_status = "completed_with_warnings"
                error = warning_detail or redact_sensitive_text(result.error)
            else:
                final_status = "succeeded"
                error = None

            self.result_ready.emit(
                {
                    "test_only": True,
                    "access_check_method": "bounded_fetch",
                    "status": final_status,
                    "error": error,
                    "row_count": result.row_count,
                    "upsert_summary": {},
                    "link_summary": None,
                    "diagnostics": result.diagnostics,
                }
            )
        except Exception as exc:
            self.error_occurred.emit(redact_sensitive_text(exc))

    def _emit_progress_from_diagnostic(self, diagnostic: Any) -> None:
        message = getattr(diagnostic, "message", None)
        if not message:
            source = getattr(diagnostic, "source_alias", "")
            status = getattr(getattr(diagnostic, "status", None), "value", None) or getattr(
                diagnostic, "status", ""
            )
            message = f"{source}: {status}".strip(": ")
        self.progress_message.emit(str(message))

"""Bounded in-memory, content-free activity trace for copyable bug reports.

Only source-controlled action/category codes and an optional boolean state are
accepted. Do not add user values, paths, names, timestamps, exception text, or
diagnostic payloads to this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import queue
import re
import stat
import threading
import time

from metroliza.shared import diagnostic_store as _diagnostic_store

MAX_EVENTS = 128
MAX_REPORT_BYTES = 16 * 1024
MAX_HISTORY_BYTES = 16 * 1024
MAX_WRITE_QUEUE = 128
BUG_REPORT_UNAVAILABLE = "Bug report could not be generated from safe diagnostic data."
_SAFE_RELEASE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:-(?:dev|rc)\.[0-9]{1,3})?\Z")
_COVERAGE_NOTE = (
    "Coverage: selected actions across application workflows; not every action is recorded. "
    "Input data, paths, names, and free-text values are not included."
)
_HISTORY_NOTE = "Activity history: retained local activity may include earlier launches."
_SESSION_NOTE = "Session boundaries: unknown; prior activity is not evidence of a crash."
_ASYNC_NOTE = "Recent activity is queued asynchronously and may not survive forced exit."
ERROR_LOG_NOTE = "Repeated error-log categories may be coalesced; detailed log text is not included."
AGENT_REPORT_GUIDANCE = (
    "",
    "## Instructions for a coding agent",
    "Inspect the source for the recorded actions, results and options; investigate the reported category.",
    "Use synthetic inputs only. Do not request or infer confidential files, values, paths or names.",
    "Attempt a relevant reproduction where possible; distinguish evidence, hypotheses and unverified behavior.",
)
_STAGE_NAME = re.compile(r"\.stage-[0-9a-f]{32}\.tmp\Z")


def _release_version(value: object) -> str:
    if type(value) is str and len(value) <= 40 and _SAFE_RELEASE.fullmatch(value):
        return value
    return "UNKNOWN"


class BugReportAction(str, Enum):
    APP_OPENED = "app_opened"
    CSV_OPENED = "csv_opened"
    CSV_LOAD_STARTED = "csv_load_started"
    CSV_LOAD_FINISHED = "csv_load_finished"
    CSV_LOAD_FAILED = "csv_load_failed"
    CSV_LOAD_CANCELLED = "csv_load_cancelled"
    FILTER_APPLIED = "filter_applied"
    GROUPING_APPLIED = "grouping_applied"
    OPTION_WORKBOOK = "option_workbook"
    OPTION_HTML = "option_html"
    OPTION_GROUPING = "option_grouping"
    OPTION_CHARTS = "option_charts"
    CHECK_CHARTS_PRESENT = "check_charts_present"
    CHECK_WORKBOOK_REQUEST_MATCH = "check_workbook_request_match"
    CHECK_FILTER_REQUEST_MATCH = "check_filter_request_match"
    CHECK_GROUPING_REQUEST_MATCH = "check_grouping_request_match"
    CHECK_CHART_REQUEST_MATCH = "check_chart_request_match"
    OUTPUT_WITHOUT_REQUESTED_CHARTS = "output_without_requested_charts"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_FINISHED = "analysis_finished"
    ANALYSIS_FINISHED_WITH_WARNINGS = "analysis_finished_with_warnings"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_CANCELLED = "analysis_cancelled"
    EXPORT_STARTED = "export_started"
    EXPORT_FINISHED = "export_finished"
    EXPORT_FAILED = "export_failed"
    EXPORT_CANCELLED = "export_cancelled"
    WORKFLOW_REPORT_IMPORT_STARTED = "workflow_report_import_started"
    WORKFLOW_REPORT_IMPORT_COMPLETED = "workflow_report_import_completed"
    WORKFLOW_REPORT_IMPORT_COMPLETED_WITH_WARNINGS = "workflow_report_import_completed_with_warnings"
    WORKFLOW_REPORT_IMPORT_FAILED = "workflow_report_import_failed"
    WORKFLOW_REPORT_IMPORT_CANCELLED = "workflow_report_import_cancelled"
    REPORT_PREFLIGHT_STARTED = "report_preflight_started"
    REPORT_PREFLIGHT_COMPLETED = "report_preflight_completed"
    REPORT_PREFLIGHT_CANCELLED = "report_preflight_cancelled"
    REPORT_PREFLIGHT_FAILED = "report_preflight_failed"
    REPORT_PREFLIGHT_RESULT_UNKNOWN = "report_preflight_result_unknown"
    REPORT_METADATA_REVIEW_STARTED = "report_metadata_review_started"
    REPORT_METADATA_REVIEW_COMPLETED = "report_metadata_review_completed"
    REPORT_METADATA_REVIEW_COMPLETED_WITH_WARNINGS = "report_metadata_review_completed_with_warnings"
    REPORT_METADATA_REVIEW_CANCELLED = "report_metadata_review_cancelled"
    REPORT_METADATA_REVIEW_FAILED = "report_metadata_review_failed"
    REPORT_METADATA_REVIEW_RESULT_UNKNOWN = "report_metadata_review_result_unknown"
    OPTION_REPORT_REVIEW_OCR = "option_report_review_ocr"
    CMM_PARSE_BACKEND_PYTHON_USED = "cmm_parse_backend_python_used"
    CMM_PARSE_BACKEND_NATIVE_USED = "cmm_parse_backend_native_used"
    CMM_PERSISTENCE_BACKEND_PYTHON_USED = "cmm_persistence_backend_python_used"
    CMM_PERSISTENCE_BACKEND_NATIVE_USED = "cmm_persistence_backend_native_used"
    CMM_BACKEND_OBSERVATION_INCOMPLETE = "cmm_backend_observation_incomplete"
    WORKFLOW_REPORT_EXPORT_STARTED = "workflow_report_export_started"
    WORKFLOW_REPORT_EXPORT_COMPLETED = "workflow_report_export_completed"
    WORKFLOW_REPORT_EXPORT_COMPLETED_WITH_FALLBACK = "workflow_report_export_completed_with_fallback"
    WORKFLOW_REPORT_EXPORT_COMPLETED_WITH_OMISSIONS = "workflow_report_export_completed_with_omissions"
    WORKFLOW_EXPORT_FILTER_DIALOG_OPENED = "workflow_export_filter_dialog_opened"
    WORKFLOW_EXPORT_FILTER_APPLIED = "workflow_export_filter_applied"
    WORKFLOW_EXPORT_FILTER_CRITERIA_ADDED = "workflow_export_filter_criteria_added"
    WORKFLOW_EXPORT_FILTER_CRITERIA_REMOVED = "workflow_export_filter_criteria_removed"
    WORKFLOW_EXPORT_FILTER_RESET = "workflow_export_filter_reset"
    WORKFLOW_EXPORT_FILTER_CANCELLED = "workflow_export_filter_cancelled"
    WORKFLOW_EXPORT_GROUPING_DIALOG_OPENED = "workflow_export_grouping_dialog_opened"
    WORKFLOW_EXPORT_GROUPING_APPLIED = "workflow_export_grouping_applied"
    WORKFLOW_EXPORT_GROUPING_CLEARED = "workflow_export_grouping_cleared"
    WORKFLOW_EXPORT_GROUP_CREATED = "workflow_export_group_created"
    WORKFLOW_EXPORT_GROUP_RENAMED = "workflow_export_group_renamed"
    WORKFLOW_EXPORT_GROUP_DELETED = "workflow_export_group_deleted"
    WORKFLOW_EXPORT_GROUP_MEMBERS_ASSIGNED = "workflow_export_group_members_assigned"
    WORKFLOW_EXPORT_GROUP_MEMBERS_UNASSIGNED = "workflow_export_group_members_unassigned"
    WORKFLOW_EXPORT_GROUPING_CANCELLED = "workflow_export_grouping_cancelled"
    WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_OPENED = "workflow_export_dashboard_visual_options_opened"
    WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_APPLIED = "workflow_export_dashboard_visual_options_applied"
    WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_CANCELLED = "workflow_export_dashboard_visual_options_cancelled"
    WORKFLOW_REPORT_EXPORT_FAILED = "workflow_report_export_failed"
    WORKFLOW_REPORT_EXPORT_CANCELLED = "workflow_report_export_cancelled"
    WORKFLOW_DATABASE_EDIT_OPENED = "workflow_database_edit_opened"
    WORKFLOW_DATABASE_EDIT_STARTED = "workflow_database_edit_started"
    WORKFLOW_DATABASE_EDIT_COMPLETED = "workflow_database_edit_completed"
    WORKFLOW_DATABASE_EDIT_FAILED = "workflow_database_edit_failed"
    WORKFLOW_MAPPING_IMPORT_STARTED = "workflow_mapping_import_started"
    WORKFLOW_MAPPING_IMPORT_COMPLETED = "workflow_mapping_import_completed"
    WORKFLOW_MAPPING_IMPORT_FAILED = "workflow_mapping_import_failed"
    WORKFLOW_MAPPING_IMPORT_CANCELLED = "workflow_mapping_import_cancelled"
    WORKFLOW_MAPPING_IMPORT_RESULT_UNKNOWN = "workflow_mapping_import_result_unknown"
    WORKFLOW_MAPPING_EXPORT_STARTED = "workflow_mapping_export_started"
    WORKFLOW_MAPPING_EXPORT_COMPLETED = "workflow_mapping_export_completed"
    WORKFLOW_MAPPING_EXPORT_FAILED = "workflow_mapping_export_failed"
    WORKFLOW_MAPPING_EXPORT_CANCELLED = "workflow_mapping_export_cancelled"
    WORKFLOW_MAPPING_EXPORT_RESULT_UNKNOWN = "workflow_mapping_export_result_unknown"
    WORKFLOW_MAPPING_CHANGE_STARTED = "workflow_mapping_change_started"
    WORKFLOW_MAPPING_CHANGE_COMPLETED = "workflow_mapping_change_completed"
    WORKFLOW_MAPPING_CHANGE_FAILED = "workflow_mapping_change_failed"
    WORKFLOW_MAPPING_ADD_STARTED = "workflow_mapping_add_started"
    WORKFLOW_MAPPING_ADD_COMPLETED = "workflow_mapping_add_completed"
    WORKFLOW_MAPPING_ADD_FAILED = "workflow_mapping_add_failed"
    WORKFLOW_MAPPING_EDIT_STARTED = "workflow_mapping_edit_started"
    WORKFLOW_MAPPING_EDIT_COMPLETED = "workflow_mapping_edit_completed"
    WORKFLOW_MAPPING_EDIT_FAILED = "workflow_mapping_edit_failed"
    WORKFLOW_MAPPING_DELETE_STARTED = "workflow_mapping_delete_started"
    WORKFLOW_MAPPING_DELETE_COMPLETED = "workflow_mapping_delete_completed"
    WORKFLOW_MAPPING_DELETE_FAILED = "workflow_mapping_delete_failed"
    OPTION_MAPPING_REPLACE_EXISTING = "option_mapping_replace_existing"
    OPTION_EXPORT_CLOUD = "option_export_cloud"
    OPTION_EXPORT_HTML = "option_export_html"
    OPTION_EXPORT_CONTEXT = "option_export_context"
    OPTION_HIDE_OK = "option_hide_ok"
    OPTION_EXPORT_FILTERS_APPLIED = "option_export_filters_applied"
    OPTION_EXPORT_GROUPING_APPLIED = "option_export_grouping_applied"
    OPTION_EXPORT_DASHBOARD_VISUALS_ENABLED = "option_export_dashboard_visuals_enabled"
    OPTION_EXPORT_FILTER_HAS_NOK_ONLY = "option_export_filter_has_nok_only"
    OPTION_EXPORT_FILTER_DATE_ALL = "option_export_filter_date_all"
    OPTION_EXPORT_FILTER_DATE_TODAY = "option_export_filter_date_today"
    OPTION_EXPORT_FILTER_DATE_YESTERDAY = "option_export_filter_date_yesterday"
    OPTION_EXPORT_FILTER_DATE_LAST_SEVEN_DAYS = "option_export_filter_date_last_seven_days"
    OPTION_EXPORT_FILTER_DATE_THIS_MONTH = "option_export_filter_date_this_month"
    OPTION_EXPORT_FILTER_DATE_CUSTOM = "option_export_filter_date_custom"
    OPTION_DASHBOARD_CHART_HISTOGRAM = "option_dashboard_chart_histogram"
    OPTION_DASHBOARD_CHART_VIOLIN = "option_dashboard_chart_violin"
    OPTION_DASHBOARD_CHART_IQR = "option_dashboard_chart_iqr"
    OPTION_DASHBOARD_CHART_SCATTER = "option_dashboard_chart_scatter"
    OPTION_DASHBOARD_STAT_ACCENT_ENABLED = "option_dashboard_stat_accent_enabled"
    OPTION_DASHBOARD_CUSTOM_PALETTE_ENABLED = "option_dashboard_custom_palette_enabled"
    OPTION_DASHBOARD_MARKER_OUTLINE_ENABLED = "option_dashboard_marker_outline_enabled"
    OPTION_DASHBOARD_RECIPE_AUTO = "option_dashboard_recipe_auto"
    OPTION_DASHBOARD_RECIPE_PROFESSIONAL_CONTRAST = "option_dashboard_recipe_professional_contrast"
    OPTION_DASHBOARD_RECIPE_COLORBLIND_DISTINCT = "option_dashboard_recipe_colorblind_distinct"
    OPTION_DASHBOARD_RECIPE_HIGH_COLOR_GROUPS = "option_dashboard_recipe_high_color_groups"
    OPTION_DASHBOARD_RECIPE_TONED_REPORT = "option_dashboard_recipe_toned_report"
    OPTION_DASHBOARD_RECIPE_SOFT_PASTEL_REVIEW = "option_dashboard_recipe_soft_pastel_review"
    OPTION_DASHBOARD_RECIPE_SCIENTIFIC_GRADIENT = "option_dashboard_recipe_scientific_gradient"
    OPTION_DASHBOARD_RECIPE_DIVERGING_NOMINAL = "option_dashboard_recipe_diverging_nominal"
    OPTION_DASHBOARD_RECIPE_PRINT = "option_dashboard_recipe_print"
    OPTION_DASHBOARD_RECIPE_HIGHLIGHT_GRADIENT = "option_dashboard_recipe_highlight_gradient"
    OPTION_DASHBOARD_RECIPE_CUSTOM = "option_dashboard_recipe_custom"
    OPTION_DASHBOARD_PALETTE_METROLIZA = "option_dashboard_palette_metroliza"
    OPTION_DASHBOARD_PALETTE_OKABE_ITO = "option_dashboard_palette_okabe_ito"
    OPTION_DASHBOARD_PALETTE_TABLEAU_TEN = "option_dashboard_palette_tableau_ten"
    OPTION_DASHBOARD_PALETTE_COLORBREWER_SET_TWO = "option_dashboard_palette_colorbrewer_set_two"
    OPTION_DASHBOARD_PALETTE_COLORBREWER_DARK_TWO = "option_dashboard_palette_colorbrewer_dark_two"
    OPTION_DASHBOARD_PALETTE_COLORBREWER_PAIRED = "option_dashboard_palette_colorbrewer_paired"
    OPTION_DASHBOARD_PALETTE_IBM_CARBON = "option_dashboard_palette_ibm_carbon"
    OPTION_DASHBOARD_PALETTE_VIRIDIS = "option_dashboard_palette_viridis"
    OPTION_DASHBOARD_PALETTE_CIVIDIS = "option_dashboard_palette_cividis"
    OPTION_DASHBOARD_PALETTE_PLASMA = "option_dashboard_palette_plasma"
    OPTION_DASHBOARD_PALETTE_MAGMA = "option_dashboard_palette_magma"
    OPTION_DASHBOARD_PALETTE_RDBU = "option_dashboard_palette_rdbu"
    OPTION_DASHBOARD_PALETTE_PUOR = "option_dashboard_palette_puor"
    OPTION_DASHBOARD_PALETTE_BRBG = "option_dashboard_palette_brbg"
    OPTION_DASHBOARD_PALETTE_CUSTOM = "option_dashboard_palette_custom"
    WORKSPACE_REPORTS_OPENED = "workspace_reports_opened"
    WORKSPACE_DATABASE_OPENED = "workspace_database_opened"
    WORKSPACE_CHARACTERISTIC_MAPPING_OPENED = "workspace_characteristic_mapping_opened"
    WORKSPACE_METADATA_ENRICHMENT_OPENED = "workspace_metadata_enrichment_opened"
    WORKSPACE_EXPORT_OPENED = "workspace_export_opened"
    WORKSPACE_CSV_OPENED = "workspace_csv_opened"
    WORKSPACE_INDUSTRIAL_OPENED = "workspace_industrial_opened"
    WORKSPACE_REALTIME_OPENED = "workspace_realtime_opened"
    WORKSPACE_PARSER_PROFILES_OPENED = "workspace_parser_profiles_opened"
    METADATA_ENRICHMENT_STARTED = "metadata_enrichment_started"
    METADATA_ENRICHMENT_FINISHED = "metadata_enrichment_finished"
    METADATA_ENRICHMENT_FINISHED_WITH_WARNINGS = "metadata_enrichment_finished_with_warnings"
    METADATA_ENRICHMENT_FAILED = "metadata_enrichment_failed"
    METADATA_ENRICHMENT_CANCELLED = "metadata_enrichment_cancelled"
    METADATA_ENRICHMENT_RESULT_UNKNOWN = "metadata_enrichment_result_unknown"
    INDUSTRIAL_SOURCES_OPENED = "industrial_sources_opened"
    INDUSTRIAL_SOURCE_PROFILE_SAVE_STARTED = "industrial_source_profile_save_started"
    INDUSTRIAL_SOURCE_PROFILE_SAVE_FINISHED = "industrial_source_profile_save_finished"
    INDUSTRIAL_SOURCE_PROFILE_SAVE_FAILED = "industrial_source_profile_save_failed"
    INDUSTRIAL_SOURCE_PROFILE_IMPORT_STARTED = "industrial_source_profile_import_started"
    INDUSTRIAL_SOURCE_PROFILE_IMPORT_FINISHED = "industrial_source_profile_import_finished"
    INDUSTRIAL_SOURCE_PROFILE_IMPORT_FAILED = "industrial_source_profile_import_failed"
    REALTIME_SOURCE_CONFIG_SAVE_STARTED = "realtime_source_config_save_started"
    REALTIME_SOURCE_CONFIG_SAVE_FINISHED = "realtime_source_config_save_finished"
    REALTIME_SOURCE_CONFIG_SAVE_FAILED = "realtime_source_config_save_failed"
    REALTIME_SOURCE_CONFIG_APPLY_STARTED = "realtime_source_config_apply_started"
    REALTIME_SOURCE_CONFIG_APPLY_FINISHED = "realtime_source_config_apply_finished"
    REALTIME_SOURCE_CONFIG_APPLY_FAILED = "realtime_source_config_apply_failed"
    INDUSTRIAL_LINK_CHANGE_STARTED = "industrial_link_change_started"
    INDUSTRIAL_LINK_CHANGE_FINISHED = "industrial_link_change_finished"
    INDUSTRIAL_LINK_CHANGE_FAILED = "industrial_link_change_failed"
    INDUSTRIAL_FILTER_APPLIED = "industrial_filter_applied"
    INDUSTRIAL_GROUPING_APPLIED = "industrial_grouping_applied"
    INDUSTRIAL_SQL_PREVIEW_STARTED = "industrial_sql_preview_started"
    INDUSTRIAL_SQL_PREVIEW_FINISHED = "industrial_sql_preview_finished"
    INDUSTRIAL_SQL_PREVIEW_FAILED = "industrial_sql_preview_failed"
    INDUSTRIAL_SQL_PREVIEW_CANCELLED = "industrial_sql_preview_cancelled"
    INDUSTRIAL_SQL_PREVIEW_RESULT_UNKNOWN = "industrial_sql_preview_result_unknown"
    INDUSTRIAL_SQL_RECIPE_LOADED = "industrial_sql_recipe_loaded"
    INDUSTRIAL_SQL_RECIPE_SAVED = "industrial_sql_recipe_saved"
    INDUSTRIAL_SQL_RECIPE_LOAD_FAILED = "industrial_sql_recipe_load_failed"
    INDUSTRIAL_SQL_RECIPE_SAVE_FAILED = "industrial_sql_recipe_save_failed"
    OPTION_INDUSTRIAL_ANALYTICS_WORKBOOK = "option_industrial_analytics_workbook"
    OPTION_INDUSTRIAL_ANALYTICS_DASHBOARD = "option_industrial_analytics_dashboard"
    OPTION_INDUSTRIAL_ANALYTICS_GROUPING = "option_industrial_analytics_grouping"
    OPTION_INDUSTRIAL_ANALYTICS_CHARTS = "option_industrial_analytics_charts"
    INDUSTRIAL_SYNC_STARTED = "industrial_sync_started"
    INDUSTRIAL_SYNC_FINISHED = "industrial_sync_finished"
    INDUSTRIAL_SYNC_FAILED = "industrial_sync_failed"
    INDUSTRIAL_SYNC_CANCELLED = "industrial_sync_cancelled"
    INDUSTRIAL_SYNC_RESULT_UNKNOWN = "industrial_sync_result_unknown"
    INDUSTRIAL_SYNC_FAILED_WITH_UNKNOWN = "industrial_sync_failed_with_unknown"
    INDUSTRIAL_ANALYSIS_STARTED = "industrial_analysis_started"
    INDUSTRIAL_ANALYSIS_FINISHED = "industrial_analysis_finished"
    INDUSTRIAL_ANALYSIS_FINISHED_WITH_WARNINGS = "industrial_analysis_finished_with_warnings"
    INDUSTRIAL_ANALYSIS_FAILED = "industrial_analysis_failed"
    INDUSTRIAL_ANALYSIS_CANCELLED = "industrial_analysis_cancelled"
    INDUSTRIAL_LINKS_REFRESH_STARTED = "industrial_links_refresh_started"
    INDUSTRIAL_LINKS_REFRESH_FINISHED = "industrial_links_refresh_finished"
    INDUSTRIAL_LINKS_REFRESH_FAILED = "industrial_links_refresh_failed"
    INDUSTRIAL_LINKS_REFRESH_CANCELLED = "industrial_links_refresh_cancelled"
    INDUSTRIAL_EXPORT_STARTED = "industrial_export_started"
    INDUSTRIAL_EXPORT_FINISHED = "industrial_export_finished"
    INDUSTRIAL_EXPORT_FAILED = "industrial_export_failed"
    INDUSTRIAL_EXPORT_CANCELLED = "industrial_export_cancelled"
    INDUSTRIAL_EXPORT_CANCEL_REQUESTED = "industrial_export_cancel_requested"
    OPTION_INDUSTRIAL_FETCH_ALL = "option_industrial_fetch_all"
    OPTION_INDUSTRIAL_SOURCE_ORDER_BY = "option_industrial_source_order_by"
    OPTION_INDUSTRIAL_LIVE_EXPORT = "option_industrial_live_export"
    OPTION_INDUSTRIAL_EXPORT_CHARTS = "option_industrial_export_charts"
    OPTION_INDUSTRIAL_EXPORT_RAW = "option_industrial_export_raw"
    OPTION_SYNC_REMEMBER_CREDENTIALS = "option_sync_remember_credentials"
    REALTIME_MONITORING_OPENED = "realtime_monitoring_opened"
    REALTIME_POLL_STARTED = "realtime_poll_started"
    REALTIME_POLL_FINISHED = "realtime_poll_finished"
    REALTIME_POLL_FAILED = "realtime_poll_failed"
    REALTIME_POLL_CANCELLED = "realtime_poll_cancelled"
    REALTIME_MONITOR_STOP_REQUESTED = "realtime_monitor_stop_requested"
    REALTIME_DASHBOARD_STARTED = "realtime_dashboard_started"
    REALTIME_DASHBOARD_FINISHED = "realtime_dashboard_finished"
    REALTIME_DASHBOARD_FAILED = "realtime_dashboard_failed"
    REALTIME_DASHBOARD_CANCELLED = "realtime_dashboard_cancelled"
    REALTIME_EVENT_ACKNOWLEDGE_STARTED = "realtime_event_acknowledge_started"
    REALTIME_EVENT_ACKNOWLEDGE_FINISHED = "realtime_event_acknowledge_finished"
    REALTIME_EVENT_ACKNOWLEDGE_FAILED = "realtime_event_acknowledge_failed"
    REALTIME_EVENT_RESOLVE_STARTED = "realtime_event_resolve_started"
    REALTIME_EVENT_RESOLVE_FINISHED = "realtime_event_resolve_finished"
    REALTIME_EVENT_RESOLVE_FAILED = "realtime_event_resolve_failed"
    REALTIME_EVENT_FALSE_POSITIVE_STARTED = "realtime_event_false_positive_started"
    REALTIME_EVENT_FALSE_POSITIVE_FINISHED = "realtime_event_false_positive_finished"
    REALTIME_EVENT_FALSE_POSITIVE_FAILED = "realtime_event_false_positive_failed"
    REALTIME_TEMPORARY_STORAGE = "realtime_temporary_storage"
    PARSER_PROFILE_VALIDATION_STARTED = "parser_profile_validation_started"
    PARSER_PROFILE_VALIDATION_FINISHED = "parser_profile_validation_finished"
    PARSER_PROFILE_VALIDATION_FAILED = "parser_profile_validation_failed"
    PARSER_PROFILE_VALIDATION_CANCELLED = "parser_profile_validation_cancelled"
    PARSER_PROFILE_INSTALL_STARTED = "parser_profile_install_started"
    PARSER_PROFILE_INSTALL_COMPLETED = "parser_profile_install_completed"
    PARSER_PROFILE_INSTALL_FAILED = "parser_profile_install_failed"
    PARSER_PROFILE_ENABLE_STATE = "parser_profile_enable_state"
    HANDLED_EXCEPTION_TIMEOUT = "handled_exception_timeout"
    HANDLED_EXCEPTION_IO = "handled_exception_io"
    HANDLED_EXCEPTION_INPUT = "handled_exception_input"
    HANDLED_EXCEPTION_MEMORY = "handled_exception_memory"
    HANDLED_EXCEPTION_OTHER = "handled_exception_other"
    APPLICATION_STARTUP_FAILED = "application_startup_failed"
    APPLICATION_RUNTIME_FAILED = "application_runtime_failed"
    LOG_ERROR_APP = "log_error_app"
    LOG_ERROR_UI = "log_error_ui"
    LOG_ERROR_PARSING = "log_error_parsing"
    LOG_ERROR_REPORTS = "log_error_reports"
    LOG_ERROR_EXPORTING = "log_error_exporting"
    LOG_ERROR_INDUSTRIAL = "log_error_industrial"
    LOG_ERROR_ANALYTICS = "log_error_analytics"
    LOG_ERROR_TABULAR = "log_error_tabular"
    LOG_ERROR_CHARTS = "log_error_charts"
    LOG_ERROR_NATIVE = "log_error_native"
    LOG_ERROR_SHARED = "log_error_shared"
    LOG_ERROR_OTHER = "log_error_other"
    PROBLEM_REPORTED = "problem_reported"


class BugReportCategory(str, Enum):
    WRONG_OUTPUT = "wrong_output"
    MISSING_OUTPUT = "missing_output"
    OPERATION_FAILED = "operation_failed"
    APP_UNRESPONSIVE = "app_unresponsive"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SafeBugReportEvent:
    action: BugReportAction
    enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class BugReportSnapshot:
    events: tuple[SafeBugReportEvent, ...]
    events_lost: bool
    previous_session_state: str = "unknown"
    clear_state: str | None = None


class PreviousSessionState(str, Enum):
    LOADING = "loading"
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    NOT_AVAILABLE = "not_available"


class HistoryClearState(str, Enum):
    PENDING = "pending"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class _QueuedHistoryEvent:
    event: SafeBugReportEvent
    generation: int


@dataclass(frozen=True, slots=True)
class _ClearHistory:
    generation: int


class _StopHistoryWorker(Enum):
    STOP = "stop"


def _decode_history(data: bytes) -> tuple[tuple[SafeBugReportEvent, ...], bool]:
    """Parse only the exact bounded persisted schema; reject the whole file otherwise."""
    if type(data) is not bytes or len(data) > MAX_HISTORY_BYTES:
        raise ValueError("invalid_history")
    payload = json.loads(data.decode("ascii"))
    if type(payload) is not dict or set(payload) != {"schema", "events", "events_lost"}:
        raise ValueError("invalid_history")
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise ValueError("invalid_history")
    if type(payload["events_lost"]) is not bool or type(payload["events"]) is not list:
        raise ValueError("invalid_history")
    if len(payload["events"]) > MAX_EVENTS:
        raise ValueError("invalid_history")
    result: list[SafeBugReportEvent] = []
    for raw in payload["events"]:
        if type(raw) is not dict or set(raw) != {"action", "enabled"}:
            raise ValueError("invalid_history")
        action, enabled = raw["action"], raw["enabled"]
        if type(action) is not str or enabled is not None and type(enabled) is not bool:
            raise ValueError("invalid_history")
        result.append(SafeBugReportEvent(BugReportAction(action), enabled))
    return tuple(result), payload["events_lost"]


class LocalBugReportHistoryStore:
    """Private, bounded history file. Its root must be explicitly injected."""

    _FILE_NAME = "activity.json"
    _LOCK_NAME = ".diagnostic-store.lock"

    def prepare_locked(self) -> bool:
        """Remove only owned, regular interrupted stage files; reject unknown entries."""
        try:
            with os.scandir(self.root) as entries:
                for index, entry in enumerate(entries):
                    if index >= 8:
                        return False
                    name = entry.name
                    if name == self._LOCK_NAME:
                        continue
                    metadata = _diagnostic_store._scanned_metadata(entry)
                    if name == self._FILE_NAME:
                        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                                or _diagnostic_store._is_reparse_or_link(metadata)
                                or os.name != "nt" and metadata.st_uid != os.getuid()):
                            return False
                        continue
                    if _STAGE_NAME.fullmatch(name):
                        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                                or _diagnostic_store._is_reparse_or_link(metadata)
                                or os.name != "nt" and metadata.st_uid != os.getuid()):
                            return False
                        Path(entry.path).unlink()
                        continue
                    return False
            return True
        except OSError:
            return False

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def load_locked(self) -> tuple[tuple[SafeBugReportEvent, ...], bool]:
        path = self.root / self._FILE_NAME
        if not path.exists():
            return (), False
        return _decode_history(_diagnostic_store._safe_file_bytes(path, MAX_HISTORY_BYTES))

    def append_locked(
        self, event: SafeBugReportEvent, *, max_events: int, events_lost: bool = False
    ) -> bool:
        try:
            events, lost = self.load_locked()
            overflow = len(events) >= max_events
            events = (*events, event)[-max_events:]
            return self._replace_locked(events, lost or overflow or events_lost)
        except Exception:
            return False

    def clear_locked(self) -> bool:
        """Atomically replace only our controlled history file with an empty schema."""
        return self._replace_locked((), False)

    def _replace_locked(self, events: tuple[SafeBugReportEvent, ...], lost: bool) -> bool:
        stage = None
        try:
            path = self.root / self._FILE_NAME
            payload = {
                "schema": 1,
                "events": [
                    {"action": item.action.value, "enabled": item.enabled}
                    for item in events
                ],
                "events_lost": lost,
            }
            data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            if len(data) > MAX_HISTORY_BYTES:
                return False
            if path.exists():
                _diagnostic_store._safe_file_bytes(path, MAX_HISTORY_BYTES)
            stage = _diagnostic_store._write_stage(self.root, data)
            os.replace(stage, path)
            stage = None
            if os.name != "nt":
                descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return True
        except Exception:
            return False
        finally:
            if stage is not None:
                try:
                    stage.unlink(missing_ok=True)
                except OSError:
                    pass


class SafeBugReportRecorder:
    """Keep bounded activity in memory and optionally persist it off the caller thread."""

    def __init__(
        self,
        *,
        max_events: int = MAX_EVENTS,
        write_queue_size: int = MAX_WRITE_QUEUE,
    ) -> None:
        if type(max_events) is not int or not 1 <= max_events <= MAX_EVENTS:
            raise ValueError("invalid safe bug report limit")
        if type(write_queue_size) is not int or not 1 <= write_queue_size <= MAX_WRITE_QUEUE:
            raise ValueError("invalid safe bug report queue limit")
        self._events: deque[SafeBugReportEvent] = deque(maxlen=max_events)
        self._events_lost = False
        self._max_events = max_events
        self._history: LocalBugReportHistoryStore | None = None
        self._queue: queue.Queue[
            _QueuedHistoryEvent | _ClearHistory | _StopHistoryWorker
        ] | None = None
        self._worker: threading.Thread | None = None
        self._closed_baseline: tuple[SafeBugReportEvent, ...] | None = None
        self._closed_root: Path | None = None
        self._write_pending = threading.Condition()
        self._pending_writes = 0
        self._previous_session_state = PreviousSessionState.NOT_AVAILABLE.value
        self._write_queue_size = write_queue_size
        self._lock = threading.RLock()
        self._history_generation = 0
        self._loss_since_clear = False
        self._clear_state: HistoryClearState | None = None

    def configure_history(self, root: Path) -> bool:
        """Start asynchronous restore/persistence. Returns false if already configured."""
        with self._lock:
            if (self._worker is not None and self._queue is None
                    and not self._worker.is_alive()):
                # An earlier bounded close may have timed out just before the
                # detached worker finished releasing its private store lock.
                self._worker = None
                self._history = None
            if self._worker is not None or self._history is not None:
                return False
            if self._closed_baseline is not None:
                late_events = tuple(
                    event for event in self._events
                    if all(event is not previous for previous in self._closed_baseline)
                )
                self._events.clear()
                if self._closed_root == Path(root):
                    # Earlier entries are on disk; only queue events that
                    # arrived after the previous worker's stop marker.
                    self._events.extend(late_events)
                else:
                    # Different roots are independent histories. Never transfer
                    # prior-root events; mark late, unassigned events as lost.
                    self._events_lost = bool(late_events)
                self._closed_baseline = None
                self._closed_root = None
                self._history_generation = 0
                self._clear_state = None
                self._loss_since_clear = False
            self._history = LocalBugReportHistoryStore(root)
            self._queue = queue.Queue(maxsize=self._write_queue_size)
            self._previous_session_state = PreviousSessionState.LOADING.value
            initial = tuple(self._events)
            for event in initial:
                try:
                    self._queue.put_nowait(_QueuedHistoryEvent(event, self._history_generation))
                    self._pending_writes += 1
                except queue.Full:
                    self._events_lost = True
                    break
            with self._write_pending:
                self._pending_writes += 1  # includes asynchronous root/restore bootstrap
            self._worker = threading.Thread(target=self._write_loop, daemon=True,
                                            name="metroliza-safe-bugreport")
            self._worker.start()
            return True

    def history_is_running(self, root: Path | None = None) -> bool:
        """Tell the UI whether this process already owns the history worker."""
        with self._lock:
            return (
                self._history is not None
                and (root is None or self._history.root == Path(root))
                and self._queue is not None
                and self._worker is not None
                and self._worker.is_alive()
            )

    def _initialize_history(self):
        assert self._history is not None
        lock = None
        if _diagnostic_store._ensure_private_root(self._history.root):
            lock = _diagnostic_store._StoreLock(self._history.root)
            if not lock.acquire():
                lock = None
        if lock is None:
            with self._lock:
                self._events_lost = True
                self._previous_session_state = PreviousSessionState.UNKNOWN.value
        else:
            if not self._history.prepare_locked():
                with self._lock:
                    self._events_lost = True
                    self._previous_session_state = PreviousSessionState.UNKNOWN.value
                lock.release()
                lock = None
            else:
                try:
                    prior, prior_lost = self._history.load_locked()
                    previous_state = (
                        PreviousSessionState.AVAILABLE.value
                        if prior else PreviousSessionState.NOT_AVAILABLE.value
                    )
                except Exception:
                    prior, prior_lost = (), True
                    previous_state = PreviousSessionState.UNKNOWN.value
                with self._lock:
                    current = tuple(self._events)
                    if self._history_generation == 0:
                        self._events.clear()
                        self._events.extend((*prior, *current)[-self._max_events:])
                        self._events_lost = (
                            self._events_lost or prior_lost
                            or len(prior) + len(current) > self._max_events
                        )
                    self._previous_session_state = previous_state
        return lock

    def _write_loop(self) -> None:
        assert self._queue is not None and self._history is not None
        work_queue = self._queue
        history = self._history
        lock = self._initialize_history()
        with self._write_pending:
            self._pending_writes -= 1
            self._write_pending.notify_all()
        while True:
            command = work_queue.get()
            try:
                if command is _StopHistoryWorker.STOP:
                    if lock is not None:
                        lock.release()
                        lock = None
                    return
                if isinstance(command, _ClearHistory):
                    complete = lock is not None and history.clear_locked()
                    with self._lock:
                        if command.generation == self._history_generation:
                            if complete:
                                self._clear_state = HistoryClearState.COMPLETE
                                self._events_lost = self._loss_since_clear
                                self._previous_session_state = (
                                    PreviousSessionState.NOT_AVAILABLE.value
                                )
                            else:
                                self._clear_state = HistoryClearState.ERROR
                                self._events_lost = True
                                self._loss_since_clear = True
                    continue
                assert isinstance(command, _QueuedHistoryEvent)
                with self._lock:
                    lost = self._events_lost
                if lock is None or not history.append_locked(
                    command.event, max_events=self._max_events, events_lost=lost
                ):
                    self._mark_events_lost(command.generation)
            finally:
                work_queue.task_done()
                with self._write_pending:
                    self._pending_writes -= 1
                    self._write_pending.notify_all()
        if lock is not None:
            lock.release()

    def record(self, action: object, *, enabled: object = None) -> bool:
        """Best-effort product hook; reject anything outside the closed schema."""
        try:
            if type(action) is not BugReportAction:
                with self._lock:
                    self._events_lost = True
                    self._loss_since_clear = True
                return False
            if enabled is not None and type(enabled) is not bool:
                with self._lock:
                    self._events_lost = True
                    self._loss_since_clear = True
                return False
            with self._lock:
                if len(self._events) == self._events.maxlen:
                    self._events_lost = True
                    self._loss_since_clear = True
                event = SafeBugReportEvent(action, enabled)
                self._events.append(event)
                if self._queue is not None:
                    with self._write_pending:
                        self._pending_writes += 1
                    try:
                        self._queue.put_nowait(
                            _QueuedHistoryEvent(event, self._history_generation)
                        )
                    except queue.Full:
                        with self._write_pending:
                            self._pending_writes -= 1
                        self._events_lost = True
                        self._loss_since_clear = True
            return True
        except Exception:
            # Diagnostics must never interrupt application work.
            with self._lock:
                self._events_lost = True
                self._loss_since_clear = True
            return False

    def snapshot(self) -> BugReportSnapshot:
        with self._lock:
            return BugReportSnapshot(tuple(self._events), self._events_lost,
                                     self._previous_session_state,
                                     self._clear_state.value if self._clear_state else None)

    def _mark_events_lost(self, generation: int) -> None:
        with self._lock:
            self._events_lost = True
            if generation == self._history_generation:
                self._loss_since_clear = True

    def clear_history(self) -> bool:
        """Queue a FIFO reset; true means pending, never that durable clearing completed."""
        with self._lock:
            if self._queue is None:
                self._clear_state = HistoryClearState.ERROR
                self._events_lost = True
                self._loss_since_clear = True
                return False
            generation = self._history_generation + 1
            with self._write_pending:
                self._pending_writes += 1
            try:
                self._queue.put_nowait(_ClearHistory(generation))
            except queue.Full:
                with self._write_pending:
                    self._pending_writes -= 1
                self._clear_state = HistoryClearState.ERROR
                self._events_lost = True
                self._loss_since_clear = True
                return False
            self._history_generation = generation
            self._clear_state = HistoryClearState.PENDING
            self._events.clear()
            self._events_lost = True
            self._loss_since_clear = False
            return True

    def close_history(self, timeout: float = 2.0) -> bool:
        """Best-effort orderly drain; forced process exit can lose queued events."""
        if not self.flush(timeout):
            return False
        with self._lock:
            worker = self._worker
            if worker is None:
                return True
            if self._queue is not None:
                try:
                    with self._write_pending:
                        self._pending_writes += 1
                    self._queue.put_nowait(_StopHistoryWorker.STOP)
                except queue.Full:
                    with self._write_pending:
                        self._pending_writes -= 1
                    return False
                self._closed_baseline = tuple(self._events)
                self._closed_root = self._history.root if self._history is not None else None
                # Later events remain in memory and will be queued on a reopen;
                # they must never be placed behind an already-enqueued stop.
                self._queue = None
        worker.join(timeout=min(max(float(timeout), 0.0), 30.0))
        if worker.is_alive():
            with self._lock:
                self._events_lost = True
                self._loss_since_clear = True
            return False
        with self._lock:
            if self._worker is worker:
                self._worker = None
                self._history = None
        return True

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait for queued writes, primarily for orderly teardown and tests."""
        if type(timeout) not in (int, float) or timeout < 0:
            return False
        import time

        end = time.monotonic() + min(float(timeout), 30.0)
        with self._write_pending:
            while self._pending_writes:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._write_pending.wait(remaining)
        return True


def _format_report_event(event: object) -> str:
    if type(event) is not SafeBugReportEvent or type(event.action) is not BugReportAction:
        raise ValueError("invalid_event")
    if event.enabled is not None and type(event.enabled) is not bool:
        raise ValueError("invalid_event")
    suffix = ""
    if event.enabled is not None:
        suffix = f" (enabled: `{str(event.enabled).lower()}`)"
    return f"- `{event.action.value}`{suffix}"


def build_bug_report_markdown(
    category: object,
    snapshot: object,
    *,
    release_version: object = None,
) -> str:
    """Serialize only fixed enum literals and bools; fail closed on bad input."""
    try:
        if type(category) is not BugReportCategory or type(snapshot) is not BugReportSnapshot:
            return BUG_REPORT_UNAVAILABLE
        if type(snapshot.events_lost) is not bool or type(snapshot.events) is not tuple:
            return BUG_REPORT_UNAVAILABLE
        if type(snapshot.previous_session_state) is not str or snapshot.previous_session_state not in {
            state.value for state in PreviousSessionState
        }:
            return BUG_REPORT_UNAVAILABLE
        if len(snapshot.events) > MAX_EVENTS:
            return BUG_REPORT_UNAVAILABLE
        lines = [
            "# Metroliza bug report",
            "",
            f"Application version: `{_release_version(release_version)}`",
            "This report serializes only fixed action/category codes and boolean states.",
            _COVERAGE_NOTE,
            _HISTORY_NOTE,
            _SESSION_NOTE,
            _ASYNC_NOTE,
            ERROR_LOG_NOTE,
            f"Previous activity restored: `{snapshot.previous_session_state}`",
            "Reproduction status: `NOT_RUN`",
            "External input data: `not included`",
            "",
            f"Category: `{category.value}`",
            f"Recorded events lost: `{str(snapshot.events_lost).lower()}`",
            "",
            "## Recent activity",
        ]
        lines.extend(_format_report_event(event) for event in snapshot.events)
        lines.extend(("", "## Reproduction", "Reproduction not performed. Input data was not captured."))
        lines.extend(AGENT_REPORT_GUIDANCE)
        report = "\n".join(lines) + "\n"
        if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
            return BUG_REPORT_UNAVAILABLE
        return report
    except Exception:
        return BUG_REPORT_UNAVAILABLE


recorder = SafeBugReportRecorder()

_LOG_ERROR_MODULES = {
    "app": BugReportAction.LOG_ERROR_APP,
    "ui": BugReportAction.LOG_ERROR_UI,
    "parsing": BugReportAction.LOG_ERROR_PARSING,
    "reports": BugReportAction.LOG_ERROR_REPORTS,
    "exporting": BugReportAction.LOG_ERROR_EXPORTING,
    "industrial": BugReportAction.LOG_ERROR_INDUSTRIAL,
    "analytics": BugReportAction.LOG_ERROR_ANALYTICS,
    "tabular": BugReportAction.LOG_ERROR_TABULAR,
    "charts": BugReportAction.LOG_ERROR_CHARTS,
    "native": BugReportAction.LOG_ERROR_NATIVE,
    "native_bridges": BugReportAction.LOG_ERROR_NATIVE,
    "shared": BugReportAction.LOG_ERROR_SHARED,
}
_ERROR_HOOK_LOCK = threading.Lock()
_error_hook: logging.Handler | None = None


class _SafeErrorLogHandler(logging.Handler):
    """Observe only fixed error-family codes; never format or save log records."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self._last_emitted: dict[BugReportAction, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name
            if (type(record.levelno) is not int or record.levelno < logging.ERROR
                    or type(name) is not str or not name.startswith("metroliza.")):
                return
            module = name.split(".", 2)[1]
            action = _LOG_ERROR_MODULES.get(module, BugReportAction.LOG_ERROR_OTHER)
            now = time.monotonic()
            last = self._last_emitted.get(action)
            if last is not None and now - last < 1.0:
                return
            self._last_emitted[action] = now
            recorder.record(action)
        except Exception:
            # Never recurse into logging or change the application outcome.
            return


def install_application_error_hook() -> None:
    """Install one bounded, local-only observer on the application logger."""
    global _error_hook
    try:
        with _ERROR_HOOK_LOCK:
            if _error_hook is not None:
                return
            hook = _SafeErrorLogHandler()
            logging.getLogger("metroliza").addHandler(hook)
            _error_hook = hook
    except Exception:
        return


def remove_application_error_hook() -> None:
    global _error_hook
    try:
        with _ERROR_HOOK_LOCK:
            if _error_hook is not None:
                logging.getLogger("metroliza").removeHandler(_error_hook)
                _error_hook.close()
                _error_hook = None
    except Exception:
        return


def record_handled_exception(exception: object) -> None:
    """Record only a closed error category, never exception data or type names."""
    try:
        if isinstance(exception, MemoryError):
            action = BugReportAction.HANDLED_EXCEPTION_MEMORY
        elif isinstance(exception, TimeoutError):
            action = BugReportAction.HANDLED_EXCEPTION_TIMEOUT
        elif isinstance(exception, OSError):
            action = BugReportAction.HANDLED_EXCEPTION_IO
        elif isinstance(exception, (ValueError, TypeError)):
            action = BugReportAction.HANDLED_EXCEPTION_INPUT
        else:
            action = BugReportAction.HANDLED_EXCEPTION_OTHER
        recorder.record(action)
    except Exception:
        # Reporting must never change how the original exception is handled.
        return

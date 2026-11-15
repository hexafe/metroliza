"""Closed, bounded v2 context. Missing observations always mean unknown.

No caller text, customer counts, paths, SQL, exception names or messages enter
this schema. UUIDs are runtime correlation tokens, never input identities.
Latest option observations are independent of the event ring and are NOT linked
to an operation unless a workflow explicitly supplied its correlation token.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import uuid

from metroliza.shared.diagnostic_events import (
    ExceptionKind, ExportFailureBackend, ExportFailureCode, ExportFailureDiagnostic,
    ExportFailureStage, WorkflowError, WorkflowOperation, WorkflowOutcome, WorkflowStage,
    export_failure_payload,
)

MAX_CONTEXT_EVENTS = 128
MAX_OPTION_SNAPSHOTS = 16
# 128 structured workflow records + 128 legacy codes + fixed option/provenance
# fields fit this finite budget. v1 retains its original 16 KiB limit.
MAX_V2_REPORT_BYTES = 128 * 1024
MAX_CONTEXT_BYTES = 112 * 1024
MAX_COUNTER = (1 << 53) - 1


class ContextModule(str, Enum):
    UNKNOWN = "unknown"
    REPORTS = "reports"
    DATABASE = "database"
    MAPPING = "mapping"
    EXPORT = "export"
    TABULAR = "tabular"
    INDUSTRIAL = "industrial"
    REALTIME = "realtime"
    PARSER_PROFILES = "parser_profiles"
    APP = "app"


class ContextSymptom(str, Enum):
    UNKNOWN = "unknown"
    FAILED = "failed"
    MISSING_OUTPUT = "missing_output"
    WRONG_OUTPUT = "wrong_output"
    EMPTY_OUTPUT = "empty_output"
    MISSING_CHARTS = "missing_charts"
    WRONG_GROUPING = "wrong_grouping"
    UI_UNRESPONSIVE = "ui_unresponsive"
    UI_LAYOUT = "ui_layout"
    UNEXPECTED_EXIT = "unexpected_exit"


class ContextBehavior(str, Enum):
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    ALL_REQUESTED_OUTPUTS = "all_requested_outputs"
    CORRECT_GROUPING = "correct_grouping"
    RESPONSIVE = "responsive"
    FAILED = "failed"
    MISSING_OUTPUT = "missing_output"
    WRONG_OUTPUT = "wrong_output"
    UNRESPONSIVE = "unresponsive"
    EXITED = "exited"


class OptionSnapshotKind(str, Enum):
    CSV_ANALYSIS = "csv_analysis"
    INDUSTRIAL_ANALYSIS = "industrial_analysis"
    REPORT_EXPORT = "report_export"
    INDUSTRIAL_EXPORT = "industrial_export"
    EXPORT_FILTER = "export_filter"
    EXPORT_GROUPING = "export_grouping"
    DASHBOARD_VISUALS = "dashboard_visuals"
    REALTIME = "realtime"
    REPORT_REVIEW = "report_review"
    DATABASE_EDIT = "database_edit"


_ANALYSIS_KEYS = frozenset({
    "workbook", "html", "separate_parameter_sheets", "chart_time_series",
    "chart_histogram", "chart_violin", "chart_box", "chart_groupstats",
    "filters_applied", "grouping_applied", "aggregation_configured", "cohort_configured",
    "source_production_cache", "source_industrial_cache", "source_csv", "source_xlsx",
})
OPTION_KEYS = {
    OptionSnapshotKind.CSV_ANALYSIS: _ANALYSIS_KEYS,
    OptionSnapshotKind.INDUSTRIAL_ANALYSIS: _ANALYSIS_KEYS,
    OptionSnapshotKind.REPORT_EXPORT: frozenset({
        "cloud", "html", "workbook", "industrial_context", "hide_ok", "summary_sheet",
        "allow_chart_skipping", "chart_line", "chart_scatter", "filters_applied",
        "grouping_applied", "group_analysis_light", "group_analysis_standard",
        "group_scope_single_reference", "group_scope_multi_reference",
        "preset_fast_diagnostics", "preset_full_report", "preset_html_dashboard_only",
    }),
    OptionSnapshotKind.INDUSTRIAL_EXPORT: frozenset({"charts", "raw", "live", "fetch_all"}),
    OptionSnapshotKind.EXPORT_FILTER: frozenset({"applied", "nok_only", "date_custom"}),
    OptionSnapshotKind.EXPORT_GROUPING: frozenset({"applied"}),
    OptionSnapshotKind.DASHBOARD_VISUALS: frozenset({
        "enabled", "histogram", "violin", "iqr", "scatter", "stat_accent",
        "custom_palette", "marker_outline",
    }),
    OptionSnapshotKind.REALTIME: frozenset({"temporary_storage"}),
    OptionSnapshotKind.REPORT_REVIEW: frozenset({"ocr"}),
    OptionSnapshotKind.DATABASE_EDIT: frozenset({
        "normalization_reference", "normalization_sample_number", "normalization_header",
        "report_updates_present", "measurement_updates_present",
    }),
}


class ContextOperationOutcome(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ExceptionCategory(str, Enum):
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    TIMEOUT = "timeout"
    IO = "io"
    INPUT = "input"
    MEMORY = "memory"
    IMPORT = "import"
    RUNTIME = "runtime"
    OTHER = "other"


class ExceptionSite(str, Enum):
    UNKNOWN = "unknown"
    REPORT_PARSER = "report_parser"
    REPORT_EXPORT = "report_export"
    EXPORT_DIALOG = "export_dialog"
    DATABASE_EDIT = "database_edit"
    TABULAR_ANALYTICS = "tabular_analytics"
    INDUSTRIAL_ANALYTICS = "industrial_analytics"
    PARSER_PROFILES = "parser_profiles"
    MAPPING = "mapping"
    REALTIME = "realtime"
    BOOTSTRAP = "bootstrap"


class OutputVerificationKind(str, Enum):
    REPORT_WORKBOOK = "report_workbook"
    ANALYTICS_WORKBOOK = "analytics_workbook"
    ANALYTICS_DASHBOARD = "analytics_dashboard"
    ANALYTICS_WORKBOOK_STAGING = "analytics_workbook_staging"
    ANALYTICS_DASHBOARD_STAGING = "analytics_dashboard_staging"


def exception_category(exception: object) -> ExceptionCategory:
    """Use static builtin classes only; never inspect a name/message/traceback."""
    for builtin, category in (
        (PermissionError, ExceptionCategory.PERMISSION),
        (FileNotFoundError, ExceptionCategory.NOT_FOUND),
        (FileExistsError, ExceptionCategory.ALREADY_EXISTS),
        (TimeoutError, ExceptionCategory.TIMEOUT),
        (OSError, ExceptionCategory.IO),
        ((ValueError, TypeError, KeyError), ExceptionCategory.INPUT),
        (MemoryError, ExceptionCategory.MEMORY),
        (ImportError, ExceptionCategory.IMPORT),
        (RuntimeError, ExceptionCategory.RUNTIME),
    ):
        if isinstance(exception, builtin):
            return category
    return ExceptionCategory.OTHER


@dataclass(frozen=True, slots=True)
class SafeBugReportProvenance:
    platform: str = "unknown"
    arch: str = "unknown"
    python: str = "unknown"
    qt: str = "unknown"
    pyqt: str = "unknown"
    runtime: str = "unknown"
    packager: str = "unknown"
    git_sha: str = "unknown"
    dirty: bool | None = None


@dataclass(frozen=True, slots=True)
class SafeWorkflowContext:
    invocation_id: uuid.UUID
    operation_id: uuid.UUID
    sequence: int
    operation: WorkflowOperation
    stage: WorkflowStage
    outcome: WorkflowOutcome
    error: WorkflowError
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SafeRequestContext:
    operation_id: uuid.UUID
    kind: OptionSnapshotKind
    outcome: ContextOperationOutcome
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SafeOutputVerification:
    kind: OutputVerificationKind
    passed: bool
    operation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SafeExportFailureContext:
    invocation_id: uuid.UUID
    operation_id: uuid.UUID
    stage: ExportFailureStage
    code: ExportFailureCode
    backend: ExportFailureBackend
    cause_kind: ExceptionKind
    errno: int | None = None
    winerror: int | None = None


def export_failure_context(failure: ExportFailureDiagnostic) -> SafeExportFailureContext:
    """Validate the source record, then project only the approved failure fields."""
    export_failure_payload(failure)
    return SafeExportFailureContext(
        failure.invocation_id, failure.operation_id, failure.stage, failure.code,
        failure.backend, failure.cause_kind, failure.errno, failure.winerror,
    )


@dataclass(frozen=True, slots=True)
class SafeContextEvent:
    session_id: uuid.UUID
    sequence: int
    relative_ms: int
    action: object = None
    enabled: bool | None = None
    workflow: SafeWorkflowContext | None = None
    exception: ExceptionCategory | None = None
    request: SafeRequestContext | None = None
    exception_site: ExceptionSite = ExceptionSite.UNKNOWN
    output_verification: SafeOutputVerification | None = None
    export_failure: SafeExportFailureContext | None = None


@dataclass(frozen=True, slots=True)
class SafeOptionSnapshot:
    session_id: uuid.UUID
    sequence: int
    relative_ms: int
    kind: OptionSnapshotKind
    options: tuple[tuple[str, bool], ...]
    operation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SafeBugReportContextSnapshot:
    events: tuple[SafeContextEvent, ...] = ()
    options: tuple[SafeOptionSnapshot, ...] = ()
    events_lost: bool = False
    snapshot_state: str = "available"
    generation: int = 0  # local preview invalidation; never serialized
    snapshots_lost: bool = False


@dataclass(frozen=True, slots=True)
class BugReportContextSelection:
    snapshot: SafeBugReportContextSnapshot
    provenance: SafeBugReportProvenance = SafeBugReportProvenance()
    module: ContextModule = ContextModule.UNKNOWN
    symptom: ContextSymptom = ContextSymptom.UNKNOWN
    expected: ContextBehavior = ContextBehavior.UNKNOWN
    observed: ContextBehavior = ContextBehavior.UNKNOWN


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise ValueError("invalid_context")


def _counter(value, *, positive=False):
    if type(value) is not int or not int(positive) <= value <= MAX_COUNTER:
        raise ValueError("invalid_context")
    return value


def _uuid(value):
    if type(value) is not str or len(value) != 36:
        raise ValueError("invalid_context")
    parsed = uuid.UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("invalid_context")
    return parsed


def _enum(enum_type, value):
    if type(value) is not str:
        raise ValueError("invalid_context")
    return enum_type(value)


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("invalid_context")
    return value


def _uuid_payload(value):
    if type(value) is not uuid.UUID or value.version != 4:
        raise ValueError("invalid_context")
    return str(value)


def _stamp(item):
    return {"session_id": _uuid_payload(item.session_id), "sequence": item.sequence, "relative_ms": item.relative_ms}


def _parse_stamp(item):
    return _uuid(item["session_id"]), _counter(item["sequence"], positive=True), _counter(item["relative_ms"])


def _workflow_payload(item):
    if (type(item) is not SafeWorkflowContext
            or any(type(value) is not enum_type for value, enum_type in (
                (item.operation, WorkflowOperation), (item.stage, WorkflowStage),
                (item.outcome, WorkflowOutcome), (item.error, WorkflowError)))):
        raise ValueError("invalid_context")
    return {
        "invocation_id": _uuid_payload(item.invocation_id), "operation_id": _uuid_payload(item.operation_id),
        "sequence": item.sequence, "operation": item.operation.value, "stage": item.stage.value,
        "outcome": item.outcome.value, "error": item.error.value, "duration_ms": item.duration_ms,
    }


def _parse_workflow(raw):
    _keys(raw, "invocation_id operation_id sequence operation stage outcome error duration_ms")
    duration = raw["duration_ms"]
    if duration is not None:
        _counter(duration)
        if duration > 86_400_000:
            raise ValueError("invalid_context")
    stage = _enum(WorkflowStage, raw["stage"])
    outcome = _enum(WorkflowOutcome, raw["outcome"])
    error = _enum(WorkflowError, raw["error"])
    if ((stage is WorkflowStage.FINISHED) != (duration is not None)
            or stage is WorkflowStage.STARTED and outcome is not WorkflowOutcome.STARTED
            or stage not in {WorkflowStage.STARTED, WorkflowStage.FINISHED}
            and outcome is not WorkflowOutcome.MILESTONE
            or stage is WorkflowStage.FINISHED
            and outcome in {WorkflowOutcome.STARTED, WorkflowOutcome.MILESTONE}
            or stage is not WorkflowStage.FINISHED and error is not WorkflowError.NONE):
        raise ValueError("invalid_context")
    return SafeWorkflowContext(
        _uuid(raw["invocation_id"]), _uuid(raw["operation_id"]),
        _counter(raw["sequence"], positive=True), _enum(WorkflowOperation, raw["operation"]),
        stage, outcome, error, duration,
    )


def _failure_payload(item):
    if (type(item) is not SafeExportFailureContext
            or any(type(value) is not enum_type for value, enum_type in (
                (item.stage, ExportFailureStage), (item.code, ExportFailureCode),
                (item.backend, ExportFailureBackend), (item.cause_kind, ExceptionKind)))):
        raise ValueError("invalid_context")
    return {
        "invocation_id": _uuid_payload(item.invocation_id),
        "operation_id": _uuid_payload(item.operation_id), "stage": item.stage.value,
        "code": item.code.value, "backend": item.backend.value,
        "cause_kind": item.cause_kind.value, "errno": item.errno, "winerror": item.winerror,
    }


def _parse_failure(raw):
    _keys(raw, "invocation_id operation_id stage code backend cause_kind errno winerror")
    for key in ("errno", "winerror"):
        if raw[key] is not None:
            _counter(raw[key])
            if raw[key] > 65535:
                raise ValueError("invalid_context")
    return SafeExportFailureContext(
        _uuid(raw["invocation_id"]), _uuid(raw["operation_id"]),
        _enum(ExportFailureStage, raw["stage"]), _enum(ExportFailureCode, raw["code"]),
        _enum(ExportFailureBackend, raw["backend"]), _enum(ExceptionKind, raw["cause_kind"]),
        raw["errno"], raw["winerror"],
    )


def _request_payload(request):
    if (type(request) is not SafeRequestContext or type(request.kind) is not OptionSnapshotKind
            or type(request.outcome) is not ContextOperationOutcome):
        raise ValueError("invalid_context")
    return {
        "operation_id": _uuid_payload(request.operation_id), "kind": request.kind.value,
        "outcome": request.outcome.value, "duration_ms": request.duration_ms,
    }


def _parse_request(request):
    _keys(request, "operation_id kind outcome duration_ms")
    outcome = _enum(ContextOperationOutcome, request["outcome"])
    duration = request["duration_ms"]
    if (outcome is ContextOperationOutcome.STARTED) != (duration is None):
        raise ValueError("invalid_context")
    if duration is not None:
        _counter(duration)
    return SafeRequestContext(
        _uuid(request["operation_id"]), _enum(OptionSnapshotKind, request["kind"]), outcome, duration,
    )


def _exception_payload(item):
    if type(item.exception) is not ExceptionCategory:
        raise ValueError("invalid_context")
    result = {"kind": "exception", "category": item.exception.value}
    # Preserve canonical pre-site v2 reports byte for byte.
    if item.exception_site is not ExceptionSite.UNKNOWN:
        result["site"] = item.exception_site.value
    return result


def _event_payload(item):
    if (type(item) is not SafeContextEvent or type(item.exception_site) is not ExceptionSite
            or sum(value is not None for value in (
                item.action, item.workflow, item.exception, item.request,
                item.output_verification, item.export_failure)) != 1
            or item.exception is None and item.exception_site is not ExceptionSite.UNKNOWN
            or item.action is None and item.enabled is not None):
        raise ValueError("invalid_context")
    result = _stamp(item)
    if item.action is not None:
        from metroliza.shared.safe_bugreport import BugReportAction
        if type(item.action) is not BugReportAction:
            raise ValueError("invalid_context")
        result.update(kind="action", action=item.action.value, enabled=item.enabled)
    elif item.workflow is not None:
        result.update(kind="workflow", workflow=_workflow_payload(item.workflow))
    elif item.exception is not None:
        result.update(_exception_payload(item))
    elif item.request is not None:
        result.update(kind="request", request=_request_payload(item.request))
    elif item.output_verification is not None:
        verification = item.output_verification
        if (type(verification) is not SafeOutputVerification
                or type(verification.kind) is not OutputVerificationKind
                or type(verification.passed) is not bool):
            raise ValueError("invalid_context")
        result.update(kind="output_verification", output_verification={
            "kind": verification.kind.value, "passed": verification.passed,
            "operation_id": (None if verification.operation_id is None
                             else _uuid_payload(verification.operation_id)),
        })
    else:
        result.update(kind="export_failure", export_failure=_failure_payload(item.export_failure))
    return result


def _parse_event(raw):
    from metroliza.shared.safe_bugreport import BugReportAction
    if type(raw) is not dict:
        raise ValueError("invalid_context")
    kind = raw.get("kind")
    base = "session_id sequence relative_ms kind "
    if kind == "action":
        _keys(raw, base + "action enabled")
        enabled = raw["enabled"]
        if enabled is not None:
            _boolean(enabled)
        return SafeContextEvent(*_parse_stamp(raw), _enum(BugReportAction, raw["action"]), enabled)
    if kind == "workflow":
        _keys(raw, base + "workflow")
        return SafeContextEvent(*_parse_stamp(raw), workflow=_parse_workflow(raw["workflow"]))
    if kind == "exception":
        _keys(raw, base + ("category site" if "site" in raw else "category"))
        site = _enum(ExceptionSite, raw["site"]) if "site" in raw else ExceptionSite.UNKNOWN
        return SafeContextEvent(*_parse_stamp(raw), exception=_enum(ExceptionCategory, raw["category"]),
                                exception_site=site)
    if kind == "request":
        _keys(raw, base + "request")
        return SafeContextEvent(*_parse_stamp(raw), request=_parse_request(raw["request"]))
    if kind == "output_verification":
        _keys(raw, base + "output_verification")
        verification = raw["output_verification"]
        _keys(verification, "kind passed operation_id")
        token = verification["operation_id"]
        return SafeContextEvent(*_parse_stamp(raw), output_verification=SafeOutputVerification(
            _enum(OutputVerificationKind, verification["kind"]), _boolean(verification["passed"]),
            None if token is None else _uuid(token),
        ))
    if kind == "export_failure":
        _keys(raw, base + "export_failure")
        return SafeContextEvent(*_parse_stamp(raw), export_failure=_parse_failure(raw["export_failure"]))
    raise ValueError("invalid_context")


def option_snapshot(kind, options, session_id, sequence, relative_ms, operation_id):
    if (type(kind) is not OptionSnapshotKind or type(options) is not dict or not options
            or any(type(key) is not str or key not in OPTION_KEYS[kind] for key in options)
            or any(type(value) is not bool for value in options.values())):
        raise ValueError("invalid_context")
    return SafeOptionSnapshot(session_id, sequence, relative_ms, kind, tuple(sorted(options.items())), operation_id)


def context_payload(snapshot):
    if (type(snapshot) is not SafeBugReportContextSnapshot or type(snapshot.events) is not tuple
            or type(snapshot.options) is not tuple or len(snapshot.events) > MAX_CONTEXT_EVENTS
            or len(snapshot.options) > MAX_OPTION_SNAPSHOTS):
        raise ValueError("invalid_context")
    for item in snapshot.options:
        if (type(item) is not SafeOptionSnapshot or type(item.kind) is not OptionSnapshotKind
                or type(item.options) is not tuple or len(item.options) > len(OPTION_KEYS[item.kind])):
            raise ValueError("invalid_context")
        if any(type(pair) is not tuple or len(pair) != 2 for pair in item.options):
            raise ValueError("invalid_context")
        if len(dict(item.options)) != len(item.options):
            raise ValueError("invalid_context")
    raw = {
        "events": [_event_payload(item) for item in snapshot.events],
        "options": [dict(_stamp(item), kind=item.kind.value, options=dict(item.options), operation_id=_uuid_payload(item.operation_id))
                    for item in snapshot.options if type(item) is SafeOptionSnapshot],
        "events_lost": snapshot.events_lost, "snapshot_state": snapshot.snapshot_state,
        "snapshots_lost": snapshot.snapshots_lost,
    }
    if len(raw["options"]) != len(snapshot.options):
        raise ValueError("invalid_context")
    # Parse what is actually serialized as the single outbound/inbound boundary.
    parse_context_payload(raw)
    if len(json.dumps(raw, ensure_ascii=True).encode("ascii")) > MAX_CONTEXT_BYTES:
        raise ValueError("context_too_large")
    return raw


def parse_context_payload(raw):
    _keys(raw, "events options events_lost snapshot_state snapshots_lost")
    if (type(raw["events"]) is not list or len(raw["events"]) > MAX_CONTEXT_EVENTS
            or type(raw["options"]) is not list or len(raw["options"]) > MAX_OPTION_SNAPSHOTS
            or type(raw["snapshot_state"]) is not str
            or raw["snapshot_state"] not in {"available", "loading", "unknown", "missing", "error"}):
        raise ValueError("invalid_context")
    events = tuple(_parse_event(item) for item in raw["events"])
    options = []
    for item in raw["options"]:
        _keys(item, "session_id sequence relative_ms kind options operation_id")
        options.append(option_snapshot(_enum(OptionSnapshotKind, item["kind"]), item["options"], *_parse_stamp(item), _uuid(item["operation_id"])))
    if len({item.operation_id for item in options}) != len(options):
        raise ValueError("invalid_context")
    last = {}
    for item in events:
        previous = last.get(item.session_id)
        if previous is not None and (item.sequence <= previous.sequence or item.relative_ms < previous.relative_ms):
            raise ValueError("invalid_context")
        last[item.session_id] = item
    return SafeBugReportContextSnapshot(events, tuple(options), _boolean(raw["events_lost"]), raw["snapshot_state"],
                                        snapshots_lost=_boolean(raw["snapshots_lost"]))


def _provenance_payload(provenance):
    if type(provenance) is not SafeBugReportProvenance:
        raise ValueError("invalid_context")
    raw = {name: getattr(provenance, name) for name in SafeBugReportProvenance.__dataclass_fields__}
    _parse_provenance(raw)
    return raw


def _parse_provenance(raw):
    _keys(raw, "platform arch python qt pyqt runtime packager git_sha dirty")
    for key, choices in {
        "platform": {"unknown", "windows", "linux", "macos"},
        "arch": {"unknown", "x86_64", "arm64"},
        "runtime": {"unknown", "source", "frozen"},
        "packager": {"unknown", "source", "pyinstaller", "nuitka"},
    }.items():
        if type(raw[key]) is not str or raw[key] not in choices:
            raise ValueError("invalid_context")
    for key in ("python", "qt", "pyqt"):
        value = raw[key]
        if type(value) is not str or (value != "unknown" and not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", value)):
            raise ValueError("invalid_context")
    sha = raw["git_sha"]
    if type(sha) is not str or sha != "unknown" and not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha):
        raise ValueError("invalid_context")
    if raw["dirty"] is not None:
        _boolean(raw["dirty"])
    return SafeBugReportProvenance(**raw)


V2_PREFIX = (
    "# Metroliza bug report v2\n\n"
    "Privacy: fixed codes, boolean options, runtime tokens and vetted build facts only.\n"
    "Missing context: unknown. Option observations do not imply operation association.\n"
    "Recent activity is queued asynchronously and may not survive forced exit.\n"
    "Reproduction status: `NOT_RUN`\nExternal input data: `not included`\n\n```json\n"
)
V2_SUFFIX = (
    "\n```\n\n## Reproduction\nReproduction not performed. Input data was not captured.\n"
    "Use synthetic inputs only; a reference scenario cannot reproduce the user's issue.\n"
    "\n## Instructions for a coding agent\n"
    "Inspect the source for the recorded actions, results and options; investigate the reported category.\n"
    "Use synthetic inputs only. Do not request or infer confidential files, values, paths or names.\n"
    "Attempt a relevant reproduction where possible; distinguish evidence, hypotheses and unverified behavior.\n"
)


def build_v2_report(category, snapshot, release_version, selection):
    from metroliza.shared.safe_bugreport import BugReportAction, BugReportCategory, BugReportSnapshot, PreviousSessionState, _release_version
    if (type(category) is not BugReportCategory or type(snapshot) is not BugReportSnapshot
            or type(selection) is not BugReportContextSelection):
        raise ValueError("invalid_context")
    for value, enum_type in ((selection.module, ContextModule), (selection.symptom, ContextSymptom),
                             (selection.expected, ContextBehavior), (selection.observed, ContextBehavior)):
        if type(value) is not enum_type:
            raise ValueError("invalid_context")
    if (type(snapshot.events) is not tuple or len(snapshot.events) > 128
            or type(snapshot.previous_session_state) is not str
            or snapshot.previous_session_state not in {state.value for state in PreviousSessionState}):
        raise ValueError("invalid_context")
    actions = []
    for event in snapshot.events:
        from metroliza.shared.safe_bugreport import SafeBugReportEvent
        if type(event) is not SafeBugReportEvent or type(event.action) is not BugReportAction:
            raise ValueError("invalid_context")
        if event.enabled is not None:
            _boolean(event.enabled)
        actions.append({"action": event.action.value, "enabled": event.enabled})
    raw = {
        "schema": 2, "release_version": _release_version(release_version), "category": category.value,
        "activity": {"events": actions, "events_lost": _boolean(snapshot.events_lost),
                     "previous_session_state": snapshot.previous_session_state},
        "context": context_payload(selection.snapshot), "provenance": _provenance_payload(selection.provenance),
        "selection": {"module": selection.module.value, "symptom": selection.symptom.value,
                      "expected": selection.expected.value, "observed": selection.observed.value},
    }
    report = V2_PREFIX + json.dumps(raw, ensure_ascii=True, sort_keys=True, indent=2) + V2_SUFFIX
    if len(report.encode("ascii")) > MAX_V2_REPORT_BYTES:
        raise ValueError("report_too_large")
    return report


def parse_v2_report(report):
    """Reject unknown keys, duplicate JSON keys, types and any non-schema text."""
    from metroliza.shared.safe_bugreport import BugReportAction, BugReportCategory, BugReportSnapshot, SafeBugReportEvent
    if (type(report) is not str or len(report.encode("utf-8")) > MAX_V2_REPORT_BYTES
            or not report.startswith(V2_PREFIX) or not report.endswith(V2_SUFFIX)):
        raise ValueError("invalid_report")
    raw = json.loads(report[len(V2_PREFIX):-len(V2_SUFFIX)], object_pairs_hook=reject_duplicate_keys)
    _keys(raw, "schema release_version category activity context provenance selection")
    if type(raw["schema"]) is not int or raw["schema"] != 2:
        raise ValueError("invalid_report")
    activity = raw["activity"]
    _keys(activity, "events events_lost previous_session_state")
    if type(activity["events"]) is not list or len(activity["events"]) > 128:
        raise ValueError("invalid_report")
    events = []
    for item in activity["events"]:
        _keys(item, "action enabled")
        if item["enabled"] is not None:
            _boolean(item["enabled"])
        events.append(SafeBugReportEvent(_enum(BugReportAction, item["action"]), item["enabled"]))
    selection = raw["selection"]
    _keys(selection, "module symptom expected observed")
    selected = BugReportContextSelection(
        parse_context_payload(raw["context"]), _parse_provenance(raw["provenance"]),
        _enum(ContextModule, selection["module"]), _enum(ContextSymptom, selection["symptom"]),
        _enum(ContextBehavior, selection["expected"]), _enum(ContextBehavior, selection["observed"]),
    )
    snapshot = BugReportSnapshot(tuple(events), _boolean(activity["events_lost"]), activity["previous_session_state"])
    # Canonical equality closes free text in framing, versions and JSON rendering.
    if build_v2_report(_enum(BugReportCategory, raw["category"]), snapshot, raw["release_version"], selected) != report:
        raise ValueError("invalid_report")
    return raw

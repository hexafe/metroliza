"""Native CSV/XLSX analytics recipes with private, closed request snapshots."""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

from metroliza.exporting.output_publication import (
    OutputPublicationCanceled, conflicting_outputs, publish_output, write_dashboard_safely,
)
from metroliza.recipes.export_service import ExportRecipeService
from metroliza.industrial.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from metroliza.industrial import industrial_analytics_state as state
from metroliza.industrial.industrial_analytics_workflow import (
    AnalyticsCancelled, run_production_cache_analytics, run_tabular_file_analytics,
)
from metroliza.recipes.contracts import (
    AnalyticsOutputPaths, DataKind, LocalBinding, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    RecipeDefinition, RecipeError, StepKind, StepSpec,
)
from metroliza.recipes.ports import PreflightResult, ResultCode, StepResult, StepStatus
from metroliza.recipes.storage import StoredRecipe
from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.shared.dashboard_interactivity import DashboardInteractivityOptions
from metroliza.tabular.contracts import GroupingAssignment
from metroliza.tabular.tabular_analytics_service import (
    TabularColumnFilter, TabularLoadCancelled, cleanup_tabular_load_result, load_tabular_analytics_file,
)

_TYPES = {cls.__name__: cls for cls in (
    state.DynamicFieldFilter, state.ProductionFilterState, state.ProductionMetricSelection,
    state.ProductionAggregationState, state.ReferenceCohortState, state.ProductionChartSelection,
    TabularColumnFilter, GroupingAssignment, DashboardInteractivityOptions,
)}
_RUNTIME_FIELDS = frozenset({"tabular_load_result", "_grouping_snapshot", "_grouping_owner"})


def _encode(value):
    if is_dataclass(value):
        if _TYPES.get(type(value).__name__) is not type(value):
            raise RecipeError("unsupported_analytics_option")
        return {"type": type(value).__name__, "fields": {
            f.name: _encode(getattr(value, f.name)) for f in fields(value) if f.init}}
    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode(item) for item in value]}
    if type(value) is list:
        return [_encode(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise RecipeError("unsupported_analytics_option")
        return {key: _encode(item) for key, item in value.items()}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise RecipeError("unsupported_analytics_option")


def _decode(value):
    if type(value) is list:
        return [_decode(item) for item in value]
    if type(value) is dict:
        if value.get("type") == "tuple":
            if set(value) != {"type", "items"} or type(value["items"]) is not list:
                raise RecipeError("unsupported_analytics_option")
            return tuple(_decode(item) for item in value["items"])
        if "type" in value:
            if set(value) != {"type", "fields"} or value["type"] not in _TYPES:
                raise RecipeError("unsupported_analytics_option")
            cls = _TYPES[value["type"]]
            allowed = {f.name for f in fields(cls) if f.init}
            if type(value["fields"]) is not dict or set(value["fields"]) != allowed:
                raise RecipeError("unsupported_analytics_option")
            return cls(**{key: _decode(item) for key, item in value["fields"].items()})
        return {key: _decode(item) for key, item in value.items()}
    return value


def _source_signature(path):
    info = Path(path).stat()
    return [str(Path(path).resolve()), info.st_size, info.st_mtime_ns]


def validate(request):
    request = validate_industrial_analytics_request(request, require_runnable=True)
    if request.source_kind == "production_cache":
        if (request.grouping_df or request.tabular_filter_expression or request.tabular_column_filters
                or request.tabular_filter_keys or request.tabular_filter_columns
                or request.timestamp_column or request.reference_column or request.sheet_name is not None
                or request.dashboard_detail_mode != "full"
                or request.dashboard_interactivity_options != DashboardInteractivityOptions()):
            raise RecipeError("unsupported_industrial_option")
    elif request.filter_state != state.ProductionFilterState():
        raise RecipeError("unsupported_tabular_production_filter")
    return request


def capabilities():
    return frozenset({"tabular_file", "production_cache", "html", "xlsx", "native_filters",
                      "native_charts", "column_remapping", "source_bound_manual_groups"})


def capture(request: IndustrialAnalyticsRequest, *, name="Analiza CSV/XLSX") -> StoredRecipe:
    request = validate(request)
    source = request.input_file if request.source_kind == "tabular_file" else request.db_file
    signature = _source_signature(source) if request.grouping_df else None
    payload = {f.name: _encode(getattr(request, f.name)) for f in fields(request)
               if f.name not in _RUNTIME_FIELDS}
    # Source and output paths are independently prompted; the snapshot contains
    # the native configuration and never a loaded frame, source SQL or credentials.
    for key in ("input_file", "db_file", "output_dashboard_file", "output_workbook_file"):
        payload[key] = ""
    payload["output_workbook_file"] = "derived" if request.output_workbook_file else ""
    raw = json.dumps({"version": 1, "request": payload, "grouping_source": signature},
                     separators=(",", ":"), allow_nan=False)
    identity = str(uuid4())
    source_key = ParameterKey.SOURCE_FILE if request.source_kind == "tabular_file" else ParameterKey.EXISTING_DATABASE
    load_kind = StepKind.LOAD_TABULAR if request.source_kind == "tabular_file" else StepKind.LOAD_INDUSTRIAL
    parameters = (
        ParameterSpec(source_key, ParameterType.PATH),
        ParameterSpec(ParameterKey.OUTPUT_FILE, ParameterType.PATH),
        ParameterSpec(ParameterKey.ANALYTICS_REQUEST, ParameterType.TEXT, ParameterMode.FIXED),
        ParameterSpec(ParameterKey.SOURCE_KIND, ParameterType.CHOICE, ParameterMode.FIXED),
        ParameterSpec(ParameterKey.COLUMN_ROLES, ParameterType.STRINGS, required=False),
    )
    definition = RecipeDefinition(identity, (
        StepSpec(load_kind, DataKind.NONE, DataKind.TABULAR),
        StepSpec(StepKind.ANALYZE_TABULAR, DataKind.TABULAR, DataKind.ARTIFACT),
        StepSpec(StepKind.VERIFY_OUTPUT, DataKind.ARTIFACT, DataKind.ARTIFACT),
    ), parameters)
    binding = LocalBinding(identity, name, values=(
        (source_key, source), (ParameterKey.OUTPUT_FILE, request.output_dashboard_file),
        (ParameterKey.ANALYTICS_REQUEST, raw), (ParameterKey.SOURCE_KIND, request.source_kind),
    ))
    from metroliza.recipes.validation import validate_binding
    validate_binding(definition, binding, complete=True)
    return StoredRecipe(definition, binding)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError("duplicate_analytics_key")
        result[key] = value
    return result


def _request_payload(plan):
    raw = plan.value(ParameterKey.ANALYTICS_REQUEST)
    if not isinstance(raw, str) or len(raw) > 8192:
        raise RecipeError("invalid_analytics_request")
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if type(payload) is not dict or set(payload) != {"version", "request", "grouping_source"}:
        raise RecipeError("invalid_analytics_request")
    if payload["version"] != 1:
        raise RecipeError("unsupported_method_version")
    values = payload["request"]
    expected = {f.name for f in fields(IndustrialAnalyticsRequest) if f.name not in _RUNTIME_FIELDS}
    if type(values) is not dict or set(values) != expected:
        raise RecipeError("invalid_analytics_request")
    return payload


def _analytics_output_paths(output, payload):
    if output is None or output.suffix.lower() != ".html":
        raise RecipeError("invalid_output")
    workbook_marker = payload["request"]["output_workbook_file"]
    if workbook_marker not in ("", "derived"):
        raise RecipeError("invalid_analytics_request")
    from metroliza.industrial.industrial_analytics_dashboard import resolve_production_dashboard_assets_dir
    return AnalyticsOutputPaths(output, output.with_suffix(".xlsx") if workbook_marker else None,
                                resolve_production_dashboard_assets_dir(output))


def analytics_output_family(binding, output):
    """Resolve every native output from the same captured method configuration."""
    return _analytics_output_paths(output, _request_payload(binding))


def _resolve_source(plan, request, payload):
    kind = plan.value(ParameterKey.SOURCE_KIND)
    if kind != request.source_kind or kind not in ("tabular_file", "production_cache"):
        raise RecipeError("invalid_analytics_source")
    source_key = ParameterKey.SOURCE_FILE if kind == "tabular_file" else ParameterKey.EXISTING_DATABASE
    source = str(plan.value(source_key) or "")
    if payload["grouping_source"] is not None and payload["grouping_source"] != _source_signature(source):
        raise RecipeError("stale_manual_grouping")
    outputs = _analytics_output_paths(plan.output_file, payload)
    workbook = str(outputs.workbook) if outputs.workbook is not None else ""
    return replace(request, input_file=source if kind == "tabular_file" else "",
                   db_file=source if kind == "production_cache" else "",
                   output_dashboard_file=str(outputs.dashboard), output_workbook_file=workbook)


def _column_remapping(plan):
    remapping = {}
    for item in plan.value(ParameterKey.COLUMN_ROLES, ()):
        old, separator, new = item.partition("=")
        if not separator or not old.strip() or not new.strip() or old.strip() in remapping:
            raise RecipeError("invalid_column_remapping")
        remapping[old.strip()] = new.strip()
    return remapping


def _remap_request(request, remapping):
    if not remapping:
        return request
    if request.tabular_filter_expression or request.grouping_df:
        raise RecipeError("remap_filter_or_manual_groups_required")
    return replace(request,
        metric_selection=tuple(replace(m, field_name=remapping.get(m.field_name, m.field_name))
                               for m in request.metric_selection),
        timestamp_column=remapping.get(request.timestamp_column, request.timestamp_column),
        reference_column=remapping.get(request.reference_column, request.reference_column),
        tabular_filter_columns=tuple(remapping.get(c, c) for c in request.tabular_filter_columns),
        tabular_column_filters=tuple(replace(f, column=remapping.get(f.column, f.column))
                                     for f in request.tabular_column_filters),
        aggregation_state=replace(request.aggregation_state,
            group_fields=tuple(remapping.get(c, c) for c in request.aggregation_state.group_fields)))


def resolve(plan):
    try:
        payload = _request_payload(plan)
        request = IndustrialAnalyticsRequest(**{key: _decode(value) for key, value in payload["request"].items()})
        request = _resolve_source(plan, request, payload)
        return validate(_remap_request(request, _column_remapping(plan)))
    except RecipeError:
        raise
    except (ValueError, TypeError, OSError, KeyError, RecursionError) as exc:
        raise RecipeError("invalid_analytics_request") from exc


class AnalyticsRecipePorts:
    """Both source kinds use the manual analytics workflow and filter parser."""
    def __init__(self):
        self._cancel = Event()
        self._requests = {}
        self._consents = {}
        self._loaded = {}
        self._signatures = {}
        self._results = {}

    def finish(self, plan):
        cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
        self._requests.pop(plan.run_id, None)
        self._consents.pop(plan.run_id, None)
        self._signatures.pop(plan.run_id, None)
        self._results.pop(plan.run_id, None)

    def cancel(self):
        self._cancel.set()
        # Loaded snapshots are retained while execute owns them; its finally is
        # the only cleanup writer. A paused preview has no loaded source.

    def preflight(self, plan, context):
        self._cancel.clear()
        try:
            request = self._validated_request(plan)
            source = request.input_file or request.db_file
            signature = _source_signature(source)
            previous = self._signatures.get(plan.run_id)
            if previous is not None and signature != previous:
                self._consents.pop(plan.run_id, None)
                return PreflightResult(False, ResultCode.SOURCE_CHANGED)
            if request.source_kind == "production_cache" and not self._cache_ready(source):
                return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True,
                                       summary=("Brak gotowego lokalnego cache Industrial.",))
            targets = [Path(request.output_dashboard_file)]
            if request.output_workbook_file:
                targets.append(Path(request.output_workbook_file))
            self._requests[plan.run_id] = request
            self._signatures[plan.run_id] = signature
            conflicts = conflicting_outputs(targets)
            if conflicts and plan.run_id not in self._consents:
                return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True, str(uuid4()),
                    (f"Zastąpienie istniejących wyników: {len(conflicts)}",), request)
            return PreflightResult(True, summary=("Natywne filtry i mapowanie zostaną sprawdzone przed publikacją.",))
        except RecipeError:
            return PreflightResult(False, ResultCode.INVALID_PLAN)
        except (OSError, ValueError, sqlite3.Error):
            return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True)

    @staticmethod
    def _cache_ready(source):
        with sqlite_readonly_connection_scope(str(source)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {"industrial_records", "industrial_record_values"}.issubset(tables)

    @staticmethod
    def _validated_request(plan):
        from metroliza.recipes.bindings import validate_plan_paths
        request = resolve(plan)
        validate_plan_paths(plan)
        return request

    def approve(self, plan, decision):
        if decision != "continue":
            return False
        try:
            request = self._validated_request(plan)
        except (RecipeError, OSError, ValueError):
            return False
        if request != self._requests.get(plan.run_id):
            return False
        targets = [request.output_dashboard_file, request.output_workbook_file]
        self._consents[plan.run_id] = ExportRecipeService.replacement_consents(p for p in targets if p)
        return True

    def execute(self, step, plan, context):
        request = self._requests.get(plan.run_id)
        if request is None:
            return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)

        def cancelled():
            return self._cancel.is_set() or context.cancelled()

        if cancelled():
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        try:
            if self._validated_request(plan) != request:
                return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)
            if _source_signature(request.input_file or request.db_file) != self._signatures[plan.run_id]:
                return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED)
            return self._execute_current(step, plan, request, context, cancelled)
        except RecipeError:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)
        except (AnalyticsCancelled, TabularLoadCancelled, OutputPublicationCanceled):
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        except Exception:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.FAILED, ResultCode.EXPORT_FAILED)

    def _execute_current(self, step, plan, request, context, cancelled):
        if step.kind in (StepKind.LOAD_TABULAR, StepKind.LOAD_INDUSTRIAL):
            return self._load_snapshot(plan, request, cancelled)
        if step.kind is StepKind.ANALYZE_TABULAR:
            return self._analyze(plan, request, context, cancelled)
        if step.kind is StepKind.VERIFY_OUTPUT:
            verified = plan.run_id in self._results and self._verify_outputs(request)
            return StepResult(StepStatus.COMPLETED if verified else StepStatus.FAILED,
                              ResultCode.SUCCESS if verified else ResultCode.OUTPUT_MISSING,
                              artifact_verified=verified)
        return StepResult(StepStatus.FAILED, ResultCode.UNSUPPORTED)

    def _load_snapshot(self, plan, request, cancelled):
        if request.source_kind != "tabular_file":
            return StepResult(StepStatus.COMPLETED)
        loaded = load_tabular_analytics_file(
            request.input_file, sheet_name=request.sheet_name,
            timestamp_column=request.timestamp_column, reference_column=request.reference_column,
            cancel_check=cancelled,
        )
        self._loaded[plan.run_id] = loaded
        names = {c.field_name for c in loaded.metric_candidates if c.numeric_ratio >= 0.8}
        if any(metric.field_name not in names for metric in request.metric_selection):
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id))
            return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)
        return StepResult(StepStatus.COMPLETED)

    @staticmethod
    def _verify_outputs(request):
        verified = ExportRecipeService.verify(Path(request.output_dashboard_file))
        if request.output_workbook_file:
            verified = verified and ExportRecipeService.verify(Path(request.output_workbook_file))
        return verified

    def _analyze(self, plan, request, context, cancelled):
        try:
            result = self._run(request, self._loaded.get(plan.run_id),
                               self._consents.get(plan.run_id, ()), cancelled, context)
            self._results[plan.run_id] = result
            if not self._verify_outputs(request):
                return StepResult(StepStatus.FAILED, ResultCode.OUTPUT_MISSING)
            warnings = bool(result.diagnostics)
            return StepResult(StepStatus.PARTIAL if warnings else StepStatus.COMPLETED,
                              ResultCode.SUCCESS, artifact_verified=True)
        finally:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))

    def _run(self, request, loaded, consents, cancelled, context):
        target = Path(request.output_dashboard_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".recipe-analytics-", dir=target.parent) as scratch:
            workbook = Path(scratch) / Path(request.output_workbook_file).name if request.output_workbook_file else None
            result_holder = []

            def writer(*, output_path, assets_dir):
                del assets_dir  # Native workflow chooses the same standard generation directory.
                kwargs = dict(output_dashboard_file=str(output_path),
                    output_workbook_file=str(workbook) if workbook else None,
                    metric_selection=request.metric_selection, aggregation_state=request.aggregation_state,
                    cohort_state=request.cohort_state, chart_selection=request.chart_selection,
                    separate_parameter_sheets=request.separate_parameter_sheets,
                    dashboard_visual_settings=request.dashboard_visual_settings,
                    cancel_check=cancelled, progress_callback=lambda _text: context.progress(0, 0))
                if request.source_kind == "tabular_file":
                    result = run_tabular_file_analytics(
                        input_file=request.input_file, tabular_load_result=loaded, sheet_name=request.sheet_name,
                        timestamp_column=request.timestamp_column, reference_column=request.reference_column,
                        tabular_filter_columns=request.tabular_filter_columns, tabular_filter_keys=request.tabular_filter_keys,
                        tabular_column_filters=request.tabular_column_filters,
                        tabular_filter_expression=request.tabular_filter_expression,
                        dashboard_detail_mode=request.dashboard_detail_mode, grouping_df=request.grouping_df,
                        grouping_default_group_label=request.grouping_default_group_label,
                        dashboard_interactivity_options=request.dashboard_interactivity_options, **kwargs)
                else:
                    result = run_production_cache_analytics(db_file=request.db_file,
                                                           filter_state=request.filter_state, **kwargs)
                result_holder.append(result)
                return {"html_dashboard_path": result.html_dashboard_path,
                        "html_dashboard_assets_path": result.html_dashboard_assets_path}

            write_dashboard_safely(writer, output_path=target, consents=consents, should_cancel=cancelled)
            if workbook:
                if cancelled():
                    raise OutputPublicationCanceled()
                publish_output(workbook, request.output_workbook_file, consents=consents)
            return result_holder[0]


def create_adapter_ports():
    return AnalyticsRecipePorts()

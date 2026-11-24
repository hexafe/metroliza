"""Native CSV/XLSX analytics recipes with private, closed request snapshots."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
import json
import sqlite3
from pathlib import Path
from threading import Event
from uuid import uuid4

from metroliza.exporting.output_publication import OutputPublicationCanceled, conflicting_outputs
from metroliza.recipes.export_service import ExportRecipeService
from metroliza.industrial.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from metroliza.industrial import industrial_analytics_state as state
from metroliza.industrial.industrial_analytics_workflow import (
    AnalyticsCancelled, run_production_cache_analytics, run_tabular_file_analytics,
)
from metroliza.industrial.tabular_output_publication import (
    TabularOutputFiles, TabularOutputPublication, publish_tabular_analysis,
)
from metroliza.recipes.contracts import (
    AnalyticsOutputPaths, DataKind, LocalBinding, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    RecipeDefinition, RecipeError, StepKind, StepSpec,
)
from metroliza.recipes.ports import PreflightResult, ResultCode, StepResult, StepStatus
from metroliza.recipes.storage import StoredRecipe
from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.shared.dashboard_interactivity import DashboardInteractivityOptions
from metroliza.tabular.column_types import normalize_column_types
from metroliza.tabular.contracts import GroupingAssignment
from metroliza.tabular.tabular_analytics_service import (
    TABULAR_DEFAULT_GROUP, TABULAR_GROUP_COLUMN, TabularColumnFilter, TabularLoadCancelled, cleanup_tabular_load_result,
    load_tabular_analytics_files,
)

_TYPES = {cls.__name__: cls for cls in (
    state.DynamicFieldFilter, state.ProductionFilterState, state.ProductionMetricSelection,
    state.ProductionAggregationState, state.ReferenceCohortState, state.ProductionChartSelection,
    TabularColumnFilter, GroupingAssignment, DashboardInteractivityOptions,
)}
_RUNTIME_FIELDS = frozenset({"tabular_load_result", "_grouping_snapshot", "_grouping_owner"})


@dataclass(frozen=True, repr=False)
class _OutputReview:
    conflicts: tuple[Path, ...]
    consents: tuple


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
    resolved = Path(path).resolve()
    info = resolved.stat()
    return [str(resolved), info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino, info.st_ctime_ns]


def _source_signatures(paths):
    return [_source_signature(path) for path in paths]


def _grouping_signature(signatures):
    # Preserve the on-disk representation of an existing single-file binding.
    return signatures[0] if len(signatures) == 1 else signatures


def _snapshot_signature(snapshot):
    return [str(Path(snapshot.path).resolve()), snapshot.size, snapshot.mtime_ns, *(snapshot.file_identity or ())]


def _expanded_file_signature(signature):
    return (isinstance(signature, list) and len(signature) == 6 and isinstance(signature[0], str)
            and all(type(value) is int for value in signature[1:]))


def _validate_manual_grouping_sources(sources, saved):
    signatures = [saved] if len(sources) == 1 else saved
    if (not isinstance(signatures, list) or len(signatures) != len(sources) or
            any(not _expanded_file_signature(signature) for signature in signatures)):
        raise RecipeError("manual_grouping_needs_review")
    if signatures != _source_signatures(sources):
        raise RecipeError("stale_manual_grouping")


def _invalid_analytics_code(error):
    if error.code in {"manual_grouping_needs_review", "stale_manual_grouping"}:
        return ResultCode.MANUAL_GROUPING_RECAPTURE_REQUIRED
    return ResultCode.INVALID_PLAN


def _plan_sources(plan):
    single = plan.value(ParameterKey.SOURCE_FILE) or plan.value(ParameterKey.EXISTING_DATABASE)
    return plan.value(ParameterKey.SOURCE_FILES, ()) or ((single,) if single else ())


def _capture_tabular_sources(request):
    loaded = request.tabular_load_result
    snapshots = getattr(loaded, "source_snapshots", ())
    sources = getattr(loaded, "source_files", ()) or tuple(snapshot.path for snapshot in snapshots)
    if sources and Path(sources[0]).resolve() != Path(request.input_file).resolve():
        raise RecipeError("invalid_analytics_source")
    sources = sources or (request.input_file,)
    signatures = _source_signatures(sources) if request.grouping_df else []
    if signatures and loaded is not None and signatures != [_snapshot_signature(snapshot) for snapshot in snapshots]:
        raise RecipeError("stale_manual_grouping")
    return sources, signatures


def _capture_grouping_identities(request):
    identities = getattr(request.tabular_load_result, "source_column_identities", {})
    fields = set(request.aggregation_state.group_fields)
    return [[field, label, occurrence] for (label, occurrence), field in identities.items() if field in fields]


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
    tabular = request.source_kind == "tabular_file"
    sources, signatures = _capture_tabular_sources(request) if tabular else ((request.db_file,), [])
    signature = _grouping_signature(signatures) if signatures else None
    payload = {f.name: _encode(getattr(request, f.name)) for f in fields(request)
               if f.name not in _RUNTIME_FIELDS}
    # Source and output paths are independently prompted; the snapshot contains
    # the native configuration and never a loaded frame, source SQL or credentials.
    for key in ("input_file", "db_file", "output_dashboard_file", "output_workbook_file"):
        payload[key] = ""
    payload["output_workbook_file"] = "derived" if request.output_workbook_file else ""
    envelope = {"version": 1, "request": payload, "grouping_source": signature}
    if tabular and (identities := _capture_grouping_identities(request)):
        envelope["grouping_identities"] = identities
    raw = json.dumps(envelope, separators=(",", ":"), allow_nan=False)
    identity = str(uuid4())
    source_key, source_type, source = ParameterKey.EXISTING_DATABASE, ParameterType.PATH, sources[0]
    if len(sources) > 1:
        source_key, source_type, source = ParameterKey.SOURCE_FILES, ParameterType.STRINGS, sources
    elif tabular:
        source_key = ParameterKey.SOURCE_FILE
    load_kind = StepKind.LOAD_TABULAR if tabular else StepKind.LOAD_INDUSTRIAL
    parameters = (
        ParameterSpec(source_key, source_type),
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
    overrides = getattr(request.tabular_load_result, "column_types", {})
    if tabular and overrides:
        spec = ParameterSpec(ParameterKey.COLUMN_TYPES, ParameterType.STRINGS, ParameterMode.FIXED)
        values = tuple(json.dumps((*key, kind), ensure_ascii=False) for key, kind in overrides.items())
        definition = replace(definition, parameters=(*definition.parameters, spec))
        binding = replace(binding, values=(*binding.values, (spec.key, values)))
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
    required = {"version", "request", "grouping_source"}
    if type(payload) is not dict or set(payload) not in (required, required | {"grouping_identities"}):
        raise RecipeError("invalid_analytics_request")
    if payload["version"] != 1:
        raise RecipeError("unsupported_method_version")
    values = payload["request"]
    expected = {f.name for f in fields(IndustrialAnalyticsRequest) if f.name not in _RUNTIME_FIELDS}
    if type(values) is not dict or set(values) != expected:
        raise RecipeError("invalid_analytics_request")
    return payload


def _grouping_identities(payload):
    rows = payload.get("grouping_identities", [])
    if not isinstance(rows, list):
        raise RecipeError("invalid_grouping_rule")
    identities = {}
    for entry in rows:
        if not isinstance(entry, list) or len(entry) != 3:
            raise RecipeError("invalid_grouping_rule")
        field, label, occurrence = entry
        if (not isinstance(field, str) or not isinstance(label, str) or type(occurrence) is not int
                or occurrence < 1 or field in identities):
            raise RecipeError("invalid_grouping_rule")
        identities[field] = (label, occurrence)
    return identities


def analytics_grouping_labels(binding):
    payload = _request_payload(binding)
    aggregation = _decode(payload["request"]["aggregation_state"])
    identities = _grouping_identities(payload)
    return tuple(identities.get(field, (field, 1))[0] for field in aggregation.group_fields
                 if field != TABULAR_GROUP_COLUMN)


def _analytics_output_paths(output, payload):
    if output is None or output.suffix.lower() != ".html":
        raise RecipeError("invalid_output")
    workbook_marker = payload["request"]["output_workbook_file"]
    if workbook_marker not in ("", "derived"):
        raise RecipeError("invalid_analytics_request")
    from metroliza.charts.export_html_dashboard import resolve_html_dashboard_assets_dir
    return AnalyticsOutputPaths(output, output.with_suffix(".xlsx") if workbook_marker else None,
                                resolve_html_dashboard_assets_dir(output))


def analytics_output_family(binding, output):
    """Resolve every native output from the same captured method configuration."""
    return _analytics_output_paths(output, _request_payload(binding))


def _resolve_source(plan, request, payload):
    kind = plan.value(ParameterKey.SOURCE_KIND)
    if kind != request.source_kind or kind not in ("tabular_file", "production_cache"):
        raise RecipeError("invalid_analytics_source")
    sources = _plan_sources(plan)
    if not sources or sum(bool(plan.value(key)) for key in (
            ParameterKey.SOURCE_FILES, ParameterKey.SOURCE_FILE, ParameterKey.EXISTING_DATABASE)) != 1:
        raise RecipeError("invalid_analytics_source")
    if kind == "production_cache" and sources != (plan.value(ParameterKey.EXISTING_DATABASE),):
        raise RecipeError("invalid_analytics_source")
    if kind == "tabular_file" and plan.value(ParameterKey.EXISTING_DATABASE):
        raise RecipeError("invalid_analytics_source")
    if request.grouping_df:
        _validate_manual_grouping_sources(sources, payload["grouping_source"])
    outputs = _analytics_output_paths(plan.output_file, payload)
    workbook = str(outputs.workbook) if outputs.workbook is not None else ""
    return replace(request, input_file=sources[0] if kind == "tabular_file" else "",
                   db_file=sources[0] if kind == "production_cache" else "",
                   output_dashboard_file=str(outputs.dashboard), output_workbook_file=workbook)


def _column_remapping(plan):
    remapping = {}
    for item in plan.value(ParameterKey.COLUMN_ROLES, ()):
        old, separator, new = item.partition("=")
        if not separator or not old.strip() or not new.strip() or old.strip() in remapping:
            raise RecipeError("invalid_column_remapping")
        remapping[old.strip()] = new.strip()
    return remapping


def _column_type_overrides(plan):
    overrides = {}
    try:
        for value in plan.value(ParameterKey.COLUMN_TYPES, ()):
            name, occurrence, kind = json.loads(value)
            key = (name, occurrence)
            if key in overrides:
                raise ValueError("duplicate_column_type")
            overrides[key] = kind
        return normalize_column_types(overrides)
    except (ValueError, TypeError, RecursionError) as exc:
        raise RecipeError("invalid_column_type_overrides") from exc


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
        self._output_reviews = {}
        self._loaded = {}
        self._signatures = {}
        self._results = {}

    def finish(self, plan):
        cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
        self._requests.pop(plan.run_id, None)
        self._consents.pop(plan.run_id, None)
        self._output_reviews.pop(plan.run_id, None)
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
            sources = _plan_sources(plan)
            signature = _source_signatures(sources)
            previous = self._signatures.get(plan.run_id)
            if previous is not None and signature != previous:
                self._consents.pop(plan.run_id, None)
                return PreflightResult(False, ResultCode.SOURCE_CHANGED)
            if request.source_kind == "production_cache" and not self._cache_ready(request.db_file):
                return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True,
                                       summary=("Brak gotowego lokalnego cache Industrial.",))
            targets = [Path(request.output_dashboard_file)]
            if request.output_workbook_file:
                targets.append(Path(request.output_workbook_file))
            self._requests[plan.run_id] = request
            self._signatures[plan.run_id] = signature
            return self._review_outputs(plan, targets)
        except RecipeError as exc:
            return PreflightResult(False, _invalid_analytics_code(exc))
        except (OSError, ValueError, sqlite3.Error):
            return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True)

    def _review_outputs(self, plan, targets):
        conflicts = tuple(dict.fromkeys(conflicting_outputs(targets)))
        review = _OutputReview(conflicts, ExportRecipeService.replacement_consents(targets))
        if conflicts and review != self._consents.get(plan.run_id):
            self._output_reviews[plan.run_id] = review
            return PreflightResult(False, ResultCode.REVIEW_REQUIRED, True, str(uuid4()), review=review)
        return PreflightResult(True, summary=("Natywne filtry i mapowanie zostaną sprawdzone przed publikacją.",))

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
        review = self._output_reviews.get(plan.run_id)
        if review is None:
            return False
        self._consents[plan.run_id] = review
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
            if _source_signatures(_plan_sources(plan)) != self._signatures[plan.run_id]:
                return StepResult(StepStatus.FAILED, ResultCode.SOURCE_CHANGED)
            return self._execute_current(step, plan, request, context, cancelled)
        except RecipeError as exc:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.FAILED, _invalid_analytics_code(exc))
        except (AnalyticsCancelled, TabularLoadCancelled, OutputPublicationCanceled):
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.CANCELLED, ResultCode.CANCELLED)
        except FileExistsError:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))
            return StepResult(StepStatus.FAILED, ResultCode.REVIEW_REQUIRED)
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
        # The workflow consumes this exact snapshot, including every selected source.
        overrides = _column_type_overrides(plan)
        loaded = load_tabular_analytics_files(
            _plan_sources(plan), sheet_name=request.sheet_name,
            timestamp_column=request.timestamp_column, reference_column=request.reference_column,
            cancel_check=cancelled, column_types=overrides,
        )
        self._loaded[plan.run_id] = loaded
        if not self._grouping_rule_supported(plan, request, loaded):
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id))
            return StepResult(StepStatus.FAILED, ResultCode.GROUPING_RULE_UNAVAILABLE)
        names = {c.field_name for c in loaded.metric_candidates}
        if loaded.unavailable_column_types or any(metric.field_name not in names for metric in request.metric_selection):
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id))
            return StepResult(StepStatus.FAILED, ResultCode.INVALID_PLAN)
        return StepResult(StepStatus.COMPLETED)

    @staticmethod
    def _grouping_rule_supported(plan, request, loaded):
        fields = set(request.aggregation_state.group_fields)
        if TABULAR_GROUP_COLUMN in fields and not (
                request.grouping_df or request.grouping_default_group_label != TABULAR_DEFAULT_GROUP):
            return False
        columns = loaded.sqlite_store.columns if loaded.sqlite_store else loaded.dataframe.columns
        if not (fields - {TABULAR_GROUP_COLUMN}).issubset(columns):
            return False
        identities = _grouping_identities(_request_payload(plan))
        remapping = _column_remapping(plan)
        for field, identity in identities.items():
            if field in remapping:
                continue
            if loaded.source_column_identities.get(identity) != field:
                return False
        return True

    @staticmethod
    def _verify_outputs(request):
        verified = ExportRecipeService.verify(Path(request.output_dashboard_file))
        if request.output_workbook_file:
            verified = verified and ExportRecipeService.verify(Path(request.output_workbook_file))
        return verified

    def _analyze(self, plan, request, context, cancelled):
        try:
            approved = self._consents.get(plan.run_id)
            result = self._run(request, self._loaded.get(plan.run_id),
                               approved.consents if approved else None, cancelled, context)
            self._results[plan.run_id] = result
            if not ExportRecipeService.verify(Path(result.html_dashboard_path)):
                return StepResult(StepStatus.FAILED, ResultCode.OUTPUT_MISSING)
            assets = result.html_dashboard_assets_path
            if request.output_workbook_file and not result.workbook_path:
                return StepResult(StepStatus.PARTIAL, ResultCode.WORKBOOK_NOT_PUBLISHED, artifact_verified=True,
                                  dashboard_assets_path=assets)
            warnings = (ResultCode.ANALYTICS_WARNINGS,) if any(
                note.severity in {"warning", "error"} for note in result.diagnostics) else ()
            return StepResult(StepStatus.COMPLETED, warnings=warnings, artifact_verified=True,
                              dashboard_assets_path=assets)
        finally:
            cleanup_tabular_load_result(self._loaded.pop(plan.run_id, None))

    def _run(self, request, loaded, consents, cancelled, context):
        outputs = TabularOutputFiles.from_paths(request.output_dashboard_file, request.output_workbook_file)
        sources = (request.input_file, request.db_file)
        if loaded is not None:
            sources += (loaded.source_file, *loaded.source_files)
            if loaded.sqlite_store is not None:
                sources += (loaded.sqlite_store.path,)
        publication = TabularOutputPublication(
            outputs, tuple(Path(path) for path in dict.fromkeys(sources) if path),
            replace_outputs=consents, allow_html_without_workbook=True,
        )

        def render(*, output_dashboard_file, output_workbook_file, output_assets_dir):
            result = self._render(request, loaded, cancelled, context, output_dashboard_file,
                                  output_workbook_file, output_assets_dir)
            if not ExportRecipeService.verify(Path(result.html_dashboard_path)):
                raise OSError("Could not verify the staged analytics dashboard.")
            if output_workbook_file and not ExportRecipeService.verify(Path(output_workbook_file)):
                return replace(result, workbook_path="", workbook_sheet_names=(), parameter_sheet_count=0)
            return result

        return publish_tabular_analysis(render, publication, should_cancel=cancelled)

    @staticmethod
    def _render(request, loaded, cancelled, context, output_dashboard_file,
                output_workbook_file, output_assets_dir):
        kwargs = dict(output_dashboard_file=output_dashboard_file, output_assets_dir=output_assets_dir,
            output_workbook_file=output_workbook_file,
            metric_selection=request.metric_selection, aggregation_state=request.aggregation_state,
            cohort_state=request.cohort_state, chart_selection=request.chart_selection,
            separate_parameter_sheets=request.separate_parameter_sheets,
            dashboard_visual_settings=request.dashboard_visual_settings,
            cancel_check=cancelled, progress_callback=lambda _text: context.progress(0, 0))
        if request.source_kind == "tabular_file":
            return run_tabular_file_analytics(
                input_file=request.input_file, tabular_load_result=loaded, sheet_name=request.sheet_name,
                timestamp_column=request.timestamp_column, reference_column=request.reference_column,
                tabular_filter_columns=request.tabular_filter_columns, tabular_filter_keys=request.tabular_filter_keys,
                tabular_column_filters=request.tabular_column_filters,
                tabular_filter_expression=request.tabular_filter_expression,
                dashboard_detail_mode=request.dashboard_detail_mode, grouping_df=request.grouping_df,
                grouping_default_group_label=request.grouping_default_group_label,
                dashboard_interactivity_options=request.dashboard_interactivity_options, **kwargs)
        return run_production_cache_analytics(db_file=request.db_file, filter_state=request.filter_state, **kwargs)


def create_adapter_ports():
    return AnalyticsRecipePorts()

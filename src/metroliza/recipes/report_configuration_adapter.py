"""Capture typed Reports settings; reconstruct through the existing query contract.

No SQL or manual report membership is persisted. Grouping rules are canonical
column names and are resolved again against the selected current source.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, fields, replace
import json
from uuid import uuid4

from metroliza.exporting.contracts import (
    AppPaths, ExportOptions, ExportRequest, validate_export_options, validate_export_request,
)
from metroliza.recipes.contracts import (
    DataKind, LocalBinding, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    RecipeDefinition, RecipeError, ResolvedRunPlan, StepKind, StepSpec,
)
from metroliza.recipes.storage import StoredRecipe
from metroliza.reports.db import sqlite_query_only_connection_scope
from metroliza.reports.report_query_service import (
    build_grouping_query, build_measurement_export_query, build_measurement_filter_query,
    restrict_to_approved_report_sources, sqlite_approved_report_export_scope,
)
from metroliza.shared.filter_state import FilterState
from metroliza.tabular.contracts import GroupingAssignment

GROUPING_COLUMNS = frozenset({"REFERENCE", "PART_NAME", "REVISION", "TEMPLATE_VARIANT", "DATE", "SAMPLE_NUMBER"})
MAX_GROUPING_REPORTS = 100_000
_FILTER_FIELDS = {f.name for f in fields(FilterState)}
_OPTION_FIELDS = {f.name for f in fields(ExportOptions)}


def _json_object(raw: str, allowed: set[str]) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RecipeError("duplicate_configuration_key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise RecipeError("invalid_configuration") from exc
    if type(value) is not dict or set(value) != allowed:
        raise RecipeError("unsupported_configuration_fields")
    return value


def _normalize_filter_values(values: dict) -> dict:
    for key, value in tuple(values.items()):
        if key.endswith("_values"):
            if type(value) not in (list, tuple) or any(type(v) is not str for v in value):
                raise RecipeError("invalid_filter_configuration")
            values[key] = tuple(value)
        elif key == "has_nok_only":
            if type(value) is not bool:
                raise RecipeError("invalid_filter_configuration")
        elif value is not None and type(value) is not str:
            raise RecipeError("invalid_filter_configuration")
    return values


def _filter_state(plan: ResolvedRunPlan) -> FilterState:
    raw = plan.value(ParameterKey.FILTER_VALUES, ())
    if raw:
        if type(raw) is not tuple or len(raw) != 1:
            raise RecipeError("invalid_filter_configuration")
        values = _json_object(raw[0], _FILTER_FIELDS)
    else:
        values = asdict(FilterState())
    values = _normalize_filter_values(values)
    for key in (ParameterKey.DATE_FROM, ParameterKey.DATE_TO):
        value = plan.value(key)
        if value is not None:
            values[key.value] = value or None
    state = FilterState(**values)
    # Existing expression parser and date/query validation remain authoritative.
    build_measurement_filter_query(**asdict(state))
    return state


def _options(plan: ResolvedRunPlan) -> ExportOptions:
    raw = plan.value(ParameterKey.EXPORT_OPTIONS)
    if raw is None:
        from metroliza.exporting.export_preset_utils import build_export_options_for_preset
        preset = str(plan.value(ParameterKey.EXPORT_PRESET, "fast_diagnostics"))
        values = build_export_options_for_preset(preset)
        options = ExportOptions(preset=preset, **values)
        return _apply_grouping_contract(plan, validate_export_options(options))
    if type(raw) is not str:
        raise RecipeError("invalid_export_configuration")
    values = _json_object(raw, _OPTION_FIELDS)
    defaults = asdict(ExportOptions())
    for key, value in values.items():
        if key == "dashboard_visual_settings":
            if value is not None and type(value) is not dict:
                raise RecipeError("invalid_export_configuration")
        elif type(value) is not type(defaults[key]):
            raise RecipeError("invalid_export_configuration")
    options = ExportOptions(**values)
    normalized = validate_export_options(options)
    if normalized != options:
        raise RecipeError("export_configuration_requires_migration")
    if normalized.export_target not in {"excel_xlsx", "html_dashboard"}:
        raise RecipeError("unsupported_export_target")
    return _apply_grouping_contract(plan, options)


def _apply_grouping_contract(plan, options):
    if plan.value(ParameterKey.GROUPING_RULES, ()):
        return replace(options, group_analysis_level="standard", generate_html_dashboard=True)
    return options


def grouped_export_configuration(binding):
    """Apply the manual grouping contract while retaining every other native option."""
    options = replace(_options(binding), group_analysis_level="standard", generate_html_dashboard=True)
    return json.dumps(asdict(options), sort_keys=True)


def ungrouped_export_configuration(binding, *, additional_html):
    """Mirror manual Clear grouping; retain unrelated captured export settings."""
    options = replace(_options(binding), group_analysis_level="off", group_analysis_scope="auto",
                      generate_html_dashboard=additional_html)
    return json.dumps(asdict(options), sort_keys=True)


def validate_report_configuration(plan: ResolvedRunPlan) -> None:
    _filter_state(plan)
    _options(plan)
    rules = plan.value(ParameterKey.GROUPING_RULES, ())
    if type(rules) is not tuple or any(rule not in GROUPING_COLUMNS for rule in rules):
        raise RecipeError("unsupported_grouping_rule")
    if len(rules) != len(set(rules)):
        raise RecipeError("duplicate_grouping_rule")


def _group_label(key: tuple[str, ...]) -> str:
    """Encode normalized tuples injectively; retain ordinary one-column labels."""
    if len(key) == 1:
        return key[0]
    return json.dumps(key, ensure_ascii=False, separators=(", ", ": "))


def _grouping(plan: ResolvedRunPlan, query: str, *, existing_identity=None, source_digests=()):
    rules = plan.value(ParameterKey.GROUPING_RULES, ())
    if not rules:
        return None
    if plan.database_file is None:
        raise RecipeError("missing_database")
    database = str(plan.database_file)
    database_scope = (sqlite_query_only_connection_scope(database, plain_path=database.startswith("\\\\"))
                      if existing_identity is None
                      else sqlite_approved_report_export_scope(database, existing_identity, source_digests))
    with database_scope as connection:
        with closing(connection.execute(build_grouping_query(query))) as cursor:
            columns = tuple(item[0] for item in cursor.description)
            if any(rule not in columns for rule in rules) or "REPORT_ID" not in columns:
                raise RecipeError("grouping_field_remap_required")
            rows = cursor.fetchmany(MAX_GROUPING_REPORTS + 1)
            if len(rows) > MAX_GROUPING_REPORTS:
                raise RecipeError("grouping_scope_limit")
    from metroliza.shared.grouping_filter_core import normalize_grouping_key
    result = []
    for row in rows:
        record = dict(zip(columns, row))
        key = normalize_grouping_key(rules, (record[column] for column in rules))
        label = _group_label(key)
        result.append(GroupingAssignment(group=label, report_id=record["REPORT_ID"]))
    return tuple(result)


def build_export_request(plan: ResolvedRunPlan, step_kind: StepKind, *, consents=(),
                         source_digests=(), existing_identity=None) -> ExportRequest:
    validate_report_configuration(plan)
    if plan.database_file is None or plan.output_file is None:
        raise RecipeError("missing_output")
    state = _filter_state(plan)
    query = build_measurement_filter_query(**asdict(state))
    if plan.appends_to_database:
        if existing_identity is None or not source_digests:
            raise RecipeError("missing_append_export_scope")
        query = restrict_to_approved_report_sources(query)
    options = _options(plan)
    html = step_kind is StepKind.EXPORT_HTML
    if step_kind not in {StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML}:
        raise RecipeError("unsupported_export_step")
    output = plan.output_file.with_suffix(".html" if html else ".xlsx")
    options = replace(options, export_target="html_dashboard" if html else "excel_xlsx",
        backend_target="html" if html else "excel", generate_html_dashboard=html,
        generate_summary_sheet=True if html else options.generate_summary_sheet)
    return validate_export_request(ExportRequest(
        AppPaths(str(plan.database_file), excel_file=None if html else str(output),
                 html_dashboard_file=str(output) if html else None), options, query,
        _grouping(plan, query, existing_identity=existing_identity, source_digests=source_digests),
        tuple(consents),
        existing_database_identity=existing_identity,
        approved_source_digests=source_digests,
    ))


def capture_export_configuration(request: ExportRequest, *, filter_state: FilterState | None = None,
                                 grouping_rules: tuple[str, ...] = ()) -> StoredRecipe:
    validated = validate_export_request(request)
    if validated.options != request.options:
        raise RecipeError("export_configuration_requires_migration")
    request = validated
    if request.options.export_target not in {"excel_xlsx", "html_dashboard"} or request.copy_output_from:
        raise RecipeError("unsupported_export_target")
    if request.filter_query:
        expected = build_measurement_filter_query(**asdict(filter_state)) if filter_state else None
        accepted = {expected} if filter_state is not None else {build_measurement_export_query()}
        if request.filter_query not in accepted:
            raise RecipeError("filter_capture_requires_typed_state")
    if request.grouping_df is not None:
        # Existing assignments do not prove equivalence to a declared rule.
        # Capture rules independently through the editor instead.
        raise RecipeError("manual_membership_not_portable")
    if type(grouping_rules) is not tuple or any(r not in GROUPING_COLUMNS for r in grouping_rules):
        raise RecipeError("unsupported_grouping_rule")
    identity = str(uuid4())
    html = request.options.export_target == "html_dashboard"
    output = request.paths.html_dashboard_file if html else request.paths.excel_file
    steps = [StepSpec(StepKind.OPEN_DATABASE, DataKind.NONE, DataKind.DATABASE)]
    current = DataKind.DATABASE
    state = filter_state or FilterState()
    params = [ParameterSpec(ParameterKey.EXISTING_DATABASE, ParameterType.PATH),
              ParameterSpec(ParameterKey.OUTPUT_FILE, ParameterType.PATH),
              ParameterSpec(ParameterKey.EXPORT_OPTIONS, ParameterType.TEXT, ParameterMode.FIXED),
              ParameterSpec(ParameterKey.FILTER_VALUES, ParameterType.STRINGS, ParameterMode.FIXED)]
    values = [(ParameterKey.EXISTING_DATABASE, request.paths.db_file),
              (ParameterKey.OUTPUT_FILE, output),
              (ParameterKey.EXPORT_OPTIONS, json.dumps(asdict(request.options), sort_keys=True)),
              (ParameterKey.FILTER_VALUES, (json.dumps(asdict(state), sort_keys=True),))]
    if filter_state is not None:
        steps.append(StepSpec(StepKind.FILTER, current, DataKind.SELECTION))
        current = DataKind.SELECTION
    if grouping_rules:
        params.append(ParameterSpec(ParameterKey.GROUPING_RULES, ParameterType.STRINGS, ParameterMode.FIXED))
        values.append((ParameterKey.GROUPING_RULES, grouping_rules))
        steps.append(StepSpec(StepKind.GROUP, current, DataKind.SELECTION))
        current = DataKind.SELECTION
    steps.append(StepSpec(StepKind.EXPORT_HTML if html else StepKind.EXPORT_MAIN, current, DataKind.ARTIFACT))
    if not html and (request.options.generate_html_dashboard or grouping_rules):
        steps.append(StepSpec(StepKind.EXPORT_HTML, DataKind.ARTIFACT, DataKind.ARTIFACT))
    steps.append(StepSpec(StepKind.VERIFY_OUTPUT, DataKind.ARTIFACT, DataKind.ARTIFACT))
    definition = RecipeDefinition(identity, tuple(steps), tuple(params))
    binding = LocalBinding(identity, "Reports", values=tuple(values))
    from metroliza.recipes.validation import validate_binding
    validate_binding(definition, binding)
    return StoredRecipe(definition, binding)

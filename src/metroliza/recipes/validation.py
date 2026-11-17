"""Fail-closed validation of the portable, linear recipe language."""
from __future__ import annotations

import math
from uuid import UUID

from .contracts import (
    FORMAT_VERSION, METHOD_VERSION, MAX_PARAMETERS, MAX_STEPS, MAX_VALUE_LENGTH,
    DataKind, DerivationRule, LocalBinding, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    PrivateValue, RecipeDefinition, RecipeError, StepKind, StepSpec,
)

BUILTIN_IDS = frozenset({"reports_excel_main", "reports_dashboard_html", "reports_append_excel_main"})
PATH_KEYS = frozenset({ParameterKey.INPUT_FOLDER, ParameterKey.OUTPUT_FILE,
    ParameterKey.DATABASE_FILE, ParameterKey.EXISTING_DATABASE, ParameterKey.SOURCE_FILE})
STRING_LIST_KEYS = frozenset({ParameterKey.COLUMNS, ParameterKey.COLUMN_ROLES,
    ParameterKey.FILTER_VALUES, ParameterKey.GROUPING_RULES})
STEP_TYPES = {
    StepKind.OPEN_DATABASE: ({DataKind.NONE}, DataKind.DATABASE),
    StepKind.PREPARE_DATABASE: ({DataKind.NONE}, DataKind.DATABASE),
    StepKind.PREPARE_EXISTING_DATABASE: ({DataKind.NONE}, DataKind.DATABASE),
    StepKind.IMPORT_REPORTS: ({DataKind.DATABASE}, DataKind.DATABASE),
    StepKind.FILTER: ({DataKind.DATABASE, DataKind.SELECTION}, DataKind.SELECTION),
    StepKind.GROUP: ({DataKind.DATABASE, DataKind.SELECTION}, DataKind.SELECTION),
    StepKind.EXPORT_MAIN: ({DataKind.DATABASE, DataKind.SELECTION}, DataKind.ARTIFACT),
    StepKind.EXPORT_HTML: ({DataKind.DATABASE, DataKind.SELECTION, DataKind.ARTIFACT}, DataKind.ARTIFACT),
    StepKind.VERIFY_OUTPUT: ({DataKind.ARTIFACT}, DataKind.ARTIFACT),
    StepKind.LOAD_INDUSTRIAL: ({DataKind.NONE}, DataKind.TABULAR),
    StepKind.LOAD_TABULAR: ({DataKind.NONE}, DataKind.TABULAR),
    StepKind.ANALYZE_TABULAR: ({DataKind.TABULAR}, DataKind.ARTIFACT),
}


def _validate_definition_header(definition: RecipeDefinition) -> None:
    if type(definition.format_version) is not int:
        raise RecipeError("bad_format")
    if definition.format_version != FORMAT_VERSION:
        raise RecipeError("newer_format" if definition.format_version > FORMAT_VERSION else "bad_format")
    if type(definition.method_version) is not int or definition.method_version != METHOD_VERSION:
        raise RecipeError("unsupported_method_version")
    if type(definition.builtin) is not bool:
        raise RecipeError("invalid_definition")
    if definition.builtin:
        if definition.recipe_id not in BUILTIN_IDS:
            raise RecipeError("invalid_builtin")
    else:
        try:
            UUID(definition.recipe_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RecipeError("invalid_recipe_id") from exc


def _validate_steps(steps: tuple[StepSpec, ...]) -> None:
    if type(steps) is not tuple or not 1 <= len(steps) <= MAX_STEPS:
        raise RecipeError("step_limit")
    seen = set()
    current = DataKind.NONE
    for step in steps:
        if not isinstance(step.kind, StepKind) or step.kind in seen:
            raise RecipeError("unknown_or_repeated_step")
        seen.add(step.kind)
        if not isinstance(step.input_kind, DataKind) or not isinstance(step.output_kind, DataKind):
            raise RecipeError("step_type_order")
        allowed, produced = STEP_TYPES[step.kind]
        if step.input_kind != current or current not in allowed or step.output_kind != produced:
            raise RecipeError("step_type_order")
        current = produced


def _validate_parameter_rule(parameter: ParameterSpec) -> None:
    if parameter.mode is ParameterMode.DERIVED:
        if (parameter.key is not ParameterKey.DATABASE_FILE or
                parameter.rule is not DerivationRule.DATABASE_FROM_OUTPUT):
            raise RecipeError("unknown_derivation")
    elif parameter.rule is not None:
        raise RecipeError("unexpected_derivation")


def _validate_parameter_type(parameter: ParameterSpec) -> None:
    if not isinstance(parameter.type, ParameterType) or not isinstance(parameter.mode, ParameterMode):
        raise RecipeError("parameter_type")
    if type(parameter.required) is not bool:
        raise RecipeError("parameter_type")
    if parameter.key in PATH_KEYS and parameter.type is not ParameterType.PATH:
        raise RecipeError("parameter_type")
    if parameter.key in STRING_LIST_KEYS and parameter.type is not ParameterType.STRINGS:
        raise RecipeError("parameter_type")
    if parameter.key is ParameterKey.METADATA_MODE and parameter.type is not ParameterType.CHOICE:
        raise RecipeError("parameter_type")
    _validate_parameter_rule(parameter)


def validate_definition(definition: RecipeDefinition) -> None:
    _validate_definition_header(definition)
    _validate_steps(definition.steps)
    if type(definition.parameters) is not tuple or len(definition.parameters) > MAX_PARAMETERS:
        raise RecipeError("parameter_limit")
    keys = set()
    for parameter in definition.parameters:
        if not isinstance(parameter.key, ParameterKey) or parameter.key in keys:
            raise RecipeError("unknown_or_repeated_parameter")
        keys.add(parameter.key)
        _validate_parameter_type(parameter)
    if definition.steps[0].kind is StepKind.PREPARE_EXISTING_DATABASE:
        _validate_append_definition(definition, keys)


def _validate_append_definition(definition, keys):
    if (StepKind.IMPORT_REPORTS not in {step.kind for step in definition.steps}
            or ParameterKey.DATABASE_FILE in keys
            or not any(spec.key is ParameterKey.EXISTING_DATABASE and spec.required
                       for spec in definition.parameters)):
        raise RecipeError("existing_database_required")


def _validate_binding_identity(definition: RecipeDefinition, binding: LocalBinding) -> None:
    if binding.recipe_id != definition.recipe_id or type(binding.name) is not str:
        raise RecipeError("binding_identity")
    if not binding.name.strip() or len(binding.name) > 200 or "\x00" in binding.name:
        raise RecipeError("binding_name")
    if type(binding.revision) is not int or binding.revision < 0:
        raise RecipeError("binding_revision")
    if type(binding.values) is not tuple or len(binding.values) > MAX_PARAMETERS:
        raise RecipeError("parameter_limit")


def _validate_value_type(kind: ParameterType, value: PrivateValue) -> None:
    types = {
        ParameterType.PATH: (str,), ParameterType.TEXT: (str,), ParameterType.CHOICE: (str,),
        ParameterType.BOOLEAN: (bool,), ParameterType.INTEGER: (int,),
        ParameterType.NUMBER: (int, float), ParameterType.STRINGS: (tuple,),
    }
    if type(value) not in types[kind]:
        raise RecipeError("binding_type")
    if kind is ParameterType.STRINGS and any(type(v) is not str for v in value):
        raise RecipeError("binding_type")
    if type(value) is float and not math.isfinite(value):
        raise RecipeError("binding_type")


def _validate_value_limits(key: ParameterKey, value: PrivateValue) -> None:
    strings = value if type(value) is tuple else (value,) if type(value) is str else ()
    if len(strings) > 256 or any(len(v) > MAX_VALUE_LENGTH or "\x00" in v for v in strings):
        raise RecipeError("value_limit")
    if key is ParameterKey.EXPORT_PRESET and value not in {
            "fast_diagnostics", "full_report", "html_dashboard_only"}:
        raise RecipeError("unsupported_preset")
    if key is ParameterKey.METADATA_MODE and value not in {"light", "complete"}:
        raise RecipeError("unsupported_metadata_mode")


def _validate_binding_values(definition: RecipeDefinition, binding: LocalBinding) -> set[ParameterKey]:
    specs = {p.key: p for p in definition.parameters}
    seen = set()
    for pair in binding.values:
        if type(pair) is not tuple or len(pair) != 2:
            raise RecipeError("binding_value")
        key, value = pair
        if not isinstance(key, ParameterKey) or key not in specs or key in seen:
            raise RecipeError("unknown_or_repeated_parameter")
        seen.add(key)
        _validate_value_type(specs[key].type, value)
        _validate_value_limits(key, value)
    return seen


def _require_binding_values(definition: RecipeDefinition, binding: LocalBinding,
                            seen: set[ParameterKey]) -> None:
    for spec in definition.parameters:
        if spec.required and spec.mode is not ParameterMode.DERIVED:
            if spec.key not in seen or binding.value(spec.key) in ("", ()):
                raise RecipeError("missing_parameter")


def validate_binding(definition: RecipeDefinition, binding: LocalBinding, *, complete: bool = False) -> None:
    validate_definition(definition)
    _validate_binding_identity(definition, binding)
    seen = _validate_binding_values(definition, binding)
    if complete:
        _require_binding_values(definition, binding, seen)

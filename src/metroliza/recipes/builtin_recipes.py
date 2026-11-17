"""Immutable templates; user edits always create a new private copy."""
from __future__ import annotations

from metroliza.shared.parse_contracts import DEFAULT_REPORTS_METADATA_MODE

from .contracts import (
    DataKind, DerivationRule, LocalBinding, ParameterKey, ParameterMode, ParameterSpec,
    ParameterType, RecipeDefinition, StepKind, StepSpec,
)

_COMMON_PARAMETERS = (
    ParameterSpec(ParameterKey.INPUT_FOLDER, ParameterType.PATH),
    ParameterSpec(ParameterKey.OUTPUT_FILE, ParameterType.PATH),
    ParameterSpec(ParameterKey.EXPORT_PRESET, ParameterType.CHOICE, ParameterMode.FIXED),
)
_NEW_DATABASE = (
    ParameterSpec(ParameterKey.DATABASE_FILE, ParameterType.PATH, ParameterMode.DERIVED,
                  rule=DerivationRule.DATABASE_FROM_OUTPUT),
)
_METADATA_OPTIONS = (ParameterSpec(ParameterKey.METADATA_MODE, ParameterType.CHOICE, required=False),)


def _definition(identity: str, export: StepKind, *, append: bool = False) -> RecipeDefinition:
    prepare = StepKind.PREPARE_EXISTING_DATABASE if append else StepKind.PREPARE_DATABASE
    database_parameters = (ParameterSpec(ParameterKey.EXISTING_DATABASE, ParameterType.PATH),) if append else _NEW_DATABASE
    parameters = _COMMON_PARAMETERS + database_parameters
    if export is StepKind.EXPORT_MAIN:
        parameters += _METADATA_OPTIONS
    return RecipeDefinition(identity, (
        StepSpec(prepare, DataKind.NONE, DataKind.DATABASE),
        StepSpec(StepKind.IMPORT_REPORTS, DataKind.DATABASE, DataKind.DATABASE),
        StepSpec(export, DataKind.DATABASE, DataKind.ARTIFACT),
        StepSpec(StepKind.VERIFY_OUTPUT, DataKind.ARTIFACT, DataKind.ARTIFACT),
    ), parameters, builtin=True)


REPORTS_EXCEL_MAIN = _definition("reports_excel_main", StepKind.EXPORT_MAIN)
REPORTS_DASHBOARD_HTML = _definition("reports_dashboard_html", StepKind.EXPORT_HTML)
REPORTS_APPEND_EXCEL_MAIN = _definition("reports_append_excel_main", StepKind.EXPORT_MAIN, append=True)
QUICK_REPORT_RECIPES = (REPORTS_EXCEL_MAIN, REPORTS_DASHBOARD_HTML)
BUILTIN_RECIPES = (*QUICK_REPORT_RECIPES, REPORTS_APPEND_EXCEL_MAIN)
BUILTIN_LABELS = {"reports_excel_main": "Raporty → Excel Main",
                  "reports_dashboard_html": "Raporty → Dashboard HTML",
                  "reports_append_excel_main": "Dopisz do bazy → Excel Main"}


def builtin_binding(definition: RecipeDefinition, input_folder: str = "", output_file: str = "",
                    *, existing_database: str = "") -> LocalBinding:
    if definition not in BUILTIN_RECIPES:
        from .contracts import RecipeError
        raise RecipeError("invalid_builtin")
    preset = "html_dashboard_only" if definition == REPORTS_DASHBOARD_HTML else "fast_diagnostics"
    values = (
        (ParameterKey.INPUT_FOLDER, input_folder), (ParameterKey.OUTPUT_FILE, output_file),
        (ParameterKey.EXPORT_PRESET, preset),
    )
    if definition != REPORTS_DASHBOARD_HTML:
        values += ((ParameterKey.METADATA_MODE, DEFAULT_REPORTS_METADATA_MODE),)
    if definition == REPORTS_APPEND_EXCEL_MAIN:
        values += ((ParameterKey.EXISTING_DATABASE, existing_database),)
    return LocalBinding(definition.recipe_id, BUILTIN_LABELS[definition.recipe_id], values=values)

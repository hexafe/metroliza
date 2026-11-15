"""Immutable templates; user edits always create a new private copy."""
from __future__ import annotations

from .contracts import (
    DataKind, DerivationRule, LocalBinding, ParameterKey, ParameterMode, ParameterSpec,
    ParameterType, RecipeDefinition, StepKind, StepSpec,
)

_PARAMETERS = (
    ParameterSpec(ParameterKey.INPUT_FOLDER, ParameterType.PATH),
    ParameterSpec(ParameterKey.OUTPUT_FILE, ParameterType.PATH),
    ParameterSpec(ParameterKey.DATABASE_FILE, ParameterType.PATH, ParameterMode.DERIVED,
                  rule=DerivationRule.DATABASE_FROM_OUTPUT),
    ParameterSpec(ParameterKey.EXPORT_PRESET, ParameterType.CHOICE, ParameterMode.FIXED),
)


def _definition(identity: str, export: StepKind) -> RecipeDefinition:
    return RecipeDefinition(identity, (
        StepSpec(StepKind.PREPARE_DATABASE, DataKind.NONE, DataKind.DATABASE),
        StepSpec(StepKind.IMPORT_REPORTS, DataKind.DATABASE, DataKind.DATABASE),
        StepSpec(export, DataKind.DATABASE, DataKind.ARTIFACT),
        StepSpec(StepKind.VERIFY_OUTPUT, DataKind.ARTIFACT, DataKind.ARTIFACT),
    ), _PARAMETERS, builtin=True)


REPORTS_EXCEL_MAIN = _definition("reports_excel_main", StepKind.EXPORT_MAIN)
REPORTS_DASHBOARD_HTML = _definition("reports_dashboard_html", StepKind.EXPORT_HTML)
BUILTIN_RECIPES = (REPORTS_EXCEL_MAIN, REPORTS_DASHBOARD_HTML)
BUILTIN_LABELS = {"reports_excel_main": "Raporty → Excel Main",
                  "reports_dashboard_html": "Raporty → Dashboard HTML"}


def builtin_binding(definition: RecipeDefinition, input_folder: str = "", output_file: str = "") -> LocalBinding:
    if definition not in BUILTIN_RECIPES:
        from .contracts import RecipeError
        raise RecipeError("invalid_builtin")
    preset = "html_dashboard_only" if definition == REPORTS_DASHBOARD_HTML else "fast_diagnostics"
    return LocalBinding(definition.recipe_id, BUILTIN_LABELS[definition.recipe_id], values=(
        (ParameterKey.INPUT_FOLDER, input_folder), (ParameterKey.OUTPUT_FILE, output_file),
        (ParameterKey.EXPORT_PRESET, preset),
    ))

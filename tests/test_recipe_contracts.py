"""Synthetic controls for the recipe language and privacy boundary."""
from dataclasses import FrozenInstanceError, replace

import pytest

from metroliza.recipes.bindings import new_output_copy, resolve_plan
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.contracts import (
    DataKind, LocalBinding, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    RecipeError, StepKind, StepSpec,
)
from metroliza.recipes.diagnostics import safe_definition_projection
from metroliza.recipes.storage import copy_recipe, definition_payload
from metroliza.recipes.validation import validate_binding, validate_definition


def plan(tmp_path):
    return resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / "output" / "Sentinel.xlsx")))


def test_snapshot_is_deeply_immutable_and_private(tmp_path):
    resolved = plan(tmp_path)
    changed = replace(resolved.binding, name="OTHER_PRIVATE_NAME")
    assert resolved.binding.name != changed.name
    assert resolved.database_file == tmp_path / "output" / "Sentinel.db"
    with pytest.raises(FrozenInstanceError):
        resolved.binding.name = "mutation"
    portable = str(definition_payload(resolved.definition))
    assert "Sentinel" not in portable and str(tmp_path) not in portable
    assert "OTHER_PRIVATE_NAME" not in str(safe_definition_projection(resolved.definition, changed))


def test_copy_has_new_identity_and_does_not_mutate_builtin(tmp_path):
    original = plan(tmp_path)
    copy = copy_recipe(original.definition, original.binding, name="Private")
    assert copy.definition.recipe_id != original.definition.recipe_id
    assert not copy.definition.builtin and original.definition.builtin
    assert copy.binding.revision == 0


@pytest.mark.parametrize("replacement,code", [
    ({"format_version": 999}, "newer_format"),
    ({"method_version": 999}, "unsupported_method_version"),
    ({"steps": ()}, "step_limit"),
    ({"steps": (StepSpec(StepKind.EXPORT_MAIN, DataKind.NONE, DataKind.ARTIFACT),)}, "step_type_order"),
    ({"steps": REPORTS_EXCEL_MAIN.steps * 2}, "unknown_or_repeated_step"),
])
def test_closed_language_rejects_invalid_plans(replacement, code):
    with pytest.raises(RecipeError, match=code):
        validate_definition(replace(REPORTS_EXCEL_MAIN, **replacement))


def test_derived_rules_and_strict_scalar_types(tmp_path):
    resolved = plan(tmp_path)
    spec = ParameterSpec(ParameterKey.INCLUDE_PLOTS, ParameterType.BOOLEAN)
    definition = replace(resolved.definition, parameters=(*resolved.definition.parameters, spec))
    binding = replace(resolved.binding, values=(*resolved.binding.values,
        (ParameterKey.INCLUDE_PLOTS, 1)))
    with pytest.raises(RecipeError, match="binding_type"):
        validate_binding(definition, binding)
    illegal = ParameterSpec(ParameterKey.INPUT_FOLDER, ParameterType.PATH, ParameterMode.DERIVED)
    with pytest.raises(RecipeError, match="unknown_derivation"):
        validate_definition(replace(definition, parameters=(illegal,)))


def test_targets_inside_input_and_case_aliases_rejected(tmp_path):
    with pytest.raises(RecipeError, match="target_inside_input"):
        resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
            str(tmp_path), str(tmp_path / "result.xlsx")))
    resolved = plan(tmp_path)
    copied = new_output_copy(resolved)
    assert copied.output_file.stem == copied.database_file.stem
    assert copied.assets_dir.name == copied.output_file.stem + "_assets"
    assert copied.run_id != resolved.run_id


def test_unknown_keys_and_mutable_values_rejected():
    binding = LocalBinding("reports_excel_main", "Private", values=((ParameterKey.COLUMNS, ["a"]),))
    with pytest.raises(RecipeError):
        validate_binding(REPORTS_EXCEL_MAIN, binding)

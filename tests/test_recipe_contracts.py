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


def test_targets_inside_filesystem_root_are_rejected(tmp_path):
    with pytest.raises(RecipeError, match="target_inside_input"):
        resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
            tmp_path.anchor, str(tmp_path / "result.xlsx")))


def test_unknown_keys_and_mutable_values_rejected():
    binding = LocalBinding("reports_excel_main", "Private", values=((ParameterKey.COLUMNS, ["a"]),))
    with pytest.raises(RecipeError):
        validate_binding(REPORTS_EXCEL_MAIN, binding)


@pytest.mark.parametrize("name", ["Result", "Result.txt", "Result.html", "Result.XLSX"])
def test_main_normalizes_output_before_deriving_entire_family(tmp_path, name):
    resolved = resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / name)))
    assert resolved.output_file == tmp_path / "Result.xlsx"
    assert resolved.database_file == tmp_path / "Result.db"
    assert resolved.binding.value(ParameterKey.OUTPUT_FILE) == str(tmp_path / "Result.xlsx")
    assert resolved.assets_dir == tmp_path / "Result_assets"


def test_html_only_normalizes_wrong_suffix_and_checks_actual_asset_alias(tmp_path):
    from metroliza.recipes.builtin_recipes import REPORTS_DASHBOARD_HTML
    definition = replace(REPORTS_DASHBOARD_HTML, parameters=(*REPORTS_DASHBOARD_HTML.parameters,
        ParameterSpec(ParameterKey.SOURCE_FILE, ParameterType.PATH, required=False)))
    binding = builtin_binding(REPORTS_DASHBOARD_HTML, str(tmp_path / "input"),
                              str(tmp_path / "Result.xlsx"))
    resolved = resolve_plan(definition, binding)
    assert resolved.output_file == tmp_path / "Result.html"
    assert resolved.database_file == tmp_path / "Result.db"
    private = replace(binding, values=(*binding.values,
        (ParameterKey.SOURCE_FILE, str(resolved.assets_dir))))
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(definition, private)


def test_normalized_case_alias_to_source_file_is_rejected_before_execution(tmp_path):
    definition = replace(REPORTS_EXCEL_MAIN, parameters=(*REPORTS_EXCEL_MAIN.parameters,
        ParameterSpec(ParameterKey.SOURCE_FILE, ParameterType.PATH, required=False)))
    binding = builtin_binding(REPORTS_EXCEL_MAIN, str(tmp_path / "input"), str(tmp_path / "Result"))
    private = replace(binding, values=(*binding.values,
        (ParameterKey.SOURCE_FILE, str(tmp_path / "result.xlsx"))))
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(definition, private)


@pytest.mark.parametrize("alias", ["case", "symlink", "hardlink"])
def test_analytics_secondary_workbook_alias_is_rejected_in_resolved_family(tmp_path, alias):
    import os
    from metroliza.industrial.contracts import IndustrialAnalyticsRequest
    from metroliza.recipes.tabular_adapter import capture
    source = tmp_path / "measurements.xlsx"
    source.write_bytes(b"source workbook must survive planning")
    output = tmp_path / "MEASUREMENTS.html" if alias == "case" else tmp_path / "result.html"
    if alias != "case":
        secondary = output.with_suffix(".xlsx")
        try:
            secondary.symlink_to(source) if alias == "symlink" else os.link(source, secondary)
        except (OSError, NotImplementedError):
            pytest.skip("filesystem alias creation unavailable")
    entry = capture(IndustrialAnalyticsRequest(source_kind="tabular_file", input_file=str(source),
        output_dashboard_file=str(output), output_workbook_file=str(output.with_suffix(".xlsx"))))
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(entry.definition, entry.binding)
    assert source.read_bytes() == b"source workbook must survive planning"


def test_analytics_native_asset_alias_is_rejected_from_same_output_family(tmp_path):
    from metroliza.industrial.contracts import IndustrialAnalyticsRequest
    from metroliza.recipes.tabular_adapter import capture
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"source workbook must survive asset planning")
    output = tmp_path / "result.html"
    try:
        (tmp_path / "result_assets").symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem symlink creation unavailable")
    entry = capture(IndustrialAnalyticsRequest(source_kind="tabular_file", input_file=str(source),
        output_dashboard_file=str(output)))
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(entry.definition, entry.binding)
    assert source.read_bytes() == b"source workbook must survive asset planning"


def test_analytics_read_cache_remains_source_when_reserving_new_output_family(tmp_path):
    from metroliza.industrial.contracts import IndustrialAnalyticsRequest
    from metroliza.recipes.bindings import _target_paths
    from metroliza.recipes.tabular_adapter import capture, resolve
    source = tmp_path / "measurements.xlsx"
    source.write_bytes(b"synthetic read-only cache")
    native = IndustrialAnalyticsRequest(source_kind="production_cache", db_file=str(source),
        output_dashboard_file=str(tmp_path / "result.html"),
        output_workbook_file=str(tmp_path / "result.xlsx"))
    entry = capture(native)
    original = resolve_plan(entry.definition, entry.binding)
    assert original.database_file == source
    assert source not in _target_paths(original)
    assert set(_target_paths(original)) == {tmp_path / "result.html", tmp_path / "result.xlsx",
                                           original.assets_dir}
    copied = new_output_copy(original)
    assert copied.database_file == source
    assert resolve(copied).db_file == str(source)
    assert resolve(copied).output_workbook_file == str(tmp_path / "result (1).xlsx")
    assert source.read_bytes() == b"synthetic read-only cache"

"""Resolve private values exactly once before a run is submitted."""
from __future__ import annotations

import ntpath
import os
from dataclasses import replace
from pathlib import Path

from .contracts import (
    LocalBinding, ParameterKey, ParameterMode, RecipeDefinition, RecipeError, ResolvedRunPlan, StepKind,
)
from .validation import PATH_KEYS, validate_binding


def path_identity(path: Path) -> str:
    """Conservatively fold Windows aliases even when planning on Linux."""
    parts = str(path.resolve(strict=False)).replace("/", "\\").split("\\")
    return ntpath.normcase("\\".join(part.rstrip(". ") for part in parts))


def paths_alias(first: Path, second: Path) -> bool:
    if path_identity(first) == path_identity(second):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _normalized_output(definition: RecipeDefinition, values: dict) -> Path | None:
    raw = values.get(ParameterKey.OUTPUT_FILE)
    if raw is None:
        return None
    output = Path(str(raw))
    kinds = {step.kind for step in definition.steps}
    if StepKind.EXPORT_MAIN in kinds:
        output = output.with_suffix(".xlsx")
    elif StepKind.EXPORT_HTML in kinds:
        output = output.with_suffix(".html")
    values[ParameterKey.OUTPUT_FILE] = str(output)
    return output


def _assets_path(definition: RecipeDefinition, output: Path | None, binding: LocalBinding) -> Path | None:
    if output is None:
        return None
    if any(step.kind is StepKind.ANALYZE_TABULAR for step in definition.steps):
        from .tabular_adapter import analytics_output_family
        return analytics_output_family(binding, output).assets
    if any(step.kind is StepKind.EXPORT_HTML for step in definition.steps):
        from metroliza.charts.export_html_dashboard import resolve_html_dashboard_assets_dir
        return resolve_html_dashboard_assets_dir(output.with_suffix(".html"))
    return output.with_name(output.stem + "_assets")


def resolve_plan(definition: RecipeDefinition, binding: LocalBinding) -> ResolvedRunPlan:
    validate_binding(definition, binding, complete=True)
    values = dict(binding.values)
    for key in PATH_KEYS:
        if key in values:
            raw = values[key]
            if not isinstance(raw, str) or not raw.strip():
                raise RecipeError("invalid_path")
            values[key] = str(Path(raw).expanduser().resolve(strict=False))
    output = _normalized_output(definition, values)
    for spec in definition.parameters:
        if spec.mode is ParameterMode.DERIVED:
            if output is None:
                raise RecipeError("missing_output")
            values[spec.key] = str(output.with_suffix(".db"))
    database_raw = values.get(ParameterKey.DATABASE_FILE, values.get(ParameterKey.EXISTING_DATABASE))
    database = Path(str(database_raw)) if database_raw else None
    source_raw = values.get(ParameterKey.INPUT_FOLDER)
    source = Path(str(source_raw)) if source_raw else None
    snapshot = replace(binding, values=tuple(values.items()))
    plan = ResolvedRunPlan(definition, snapshot, source, output, database, _assets_path(definition, output, snapshot))
    validate_plan_paths(plan)
    return plan


def _writes_database(plan: ResolvedRunPlan) -> bool:
    return any(s.kind in {StepKind.PREPARE_DATABASE, StepKind.IMPORT_REPORTS}
               for s in plan.definition.steps)


def _target_paths(plan: ResolvedRunPlan) -> tuple[Path, ...]:
    targets = [p for p in (plan.output_file, plan.assets_dir) if p is not None]
    if _writes_database(plan) and plan.database_file is not None:
        targets.append(plan.database_file)
    if any(step.kind is StepKind.ANALYZE_TABULAR for step in plan.definition.steps):
        from .tabular_adapter import analytics_output_family
        outputs = analytics_output_family(plan.binding, plan.output_file)
        targets.extend(p for p in (outputs.dashboard, outputs.workbook, outputs.assets) if p is not None)
    if plan.output_file is not None and any(s.kind is StepKind.EXPORT_HTML for s in plan.definition.steps):
        html = plan.output_file.with_suffix(".html")
        targets.extend((html, html.with_name(html.stem + "_assets")))
    return tuple(dict.fromkeys(targets))


def _validate_source_target(plan: ResolvedRunPlan, path: Path) -> None:
    sources = [plan.value(ParameterKey.SOURCE_FILE)]
    if not _writes_database(plan):
        sources.extend((plan.value(ParameterKey.EXISTING_DATABASE), plan.database_file))
    if any(source and paths_alias(path, Path(str(source))) for source in sources):
        raise RecipeError("source_alias")
    if plan.input_folder is None:
        return
    if paths_alias(path, plan.input_folder):
        raise RecipeError("source_alias")
    source_identity = path_identity(plan.input_folder)
    if path_identity(path).startswith(source_identity.rstrip("\\") + "\\"):
        raise RecipeError("target_inside_input")


def validate_plan_paths(plan: ResolvedRunPlan, active_database: Path | None = None) -> None:
    targets = _target_paths(plan)
    for index, path in enumerate(targets):
        if any(paths_alias(path, other) for other in targets[index + 1:]):
            raise RecipeError("target_alias")
        if active_database is not None and paths_alias(path, active_database) and (
                path != plan.database_file or _writes_database(plan)):
            raise RecipeError("active_database_alias")
        _validate_source_target(plan, path)


def _copy_is_free(plan: ResolvedRunPlan) -> bool:
    from metroliza.exporting.output_publication import conflicting_outputs
    targets = [p for p in _target_paths(plan) if p != plan.database_file]
    if _writes_database(plan) and plan.database_file is not None:
        database = plan.database_file
        targets.extend((database, Path(str(database) + "-wal"), Path(str(database) + "-shm")))
    return not conflicting_outputs(targets)


def new_output_copy(plan: ResolvedRunPlan) -> ResolvedRunPlan:
    if plan.output_file is None:
        raise RecipeError("missing_output")
    original = plan.output_file
    for index in range(1, 10001):
        output = original.with_name(f"{original.stem} ({index}){original.suffix}")
        values = dict(plan.binding.values)
        values[ParameterKey.OUTPUT_FILE] = str(output)
        if _writes_database(plan):
            values[ParameterKey.DATABASE_FILE] = str(output.with_suffix(".db"))
        binding = replace(plan.binding, values=tuple(values.items()))
        candidate = replace(resolve_plan(plan.definition, binding), flow_id=plan.flow_id)
        if _copy_is_free(candidate):
            return candidate
    raise RecipeError("copy_limit")

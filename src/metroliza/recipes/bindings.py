"""Resolve private values exactly once before a run is submitted."""
from __future__ import annotations

import ntpath
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

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


def resolve_plan(definition: RecipeDefinition, binding: LocalBinding) -> ResolvedRunPlan:
    validate_binding(definition, binding, complete=True)
    values = dict(binding.values)
    for key in PATH_KEYS:
        if key in values:
            raw = values[key]
            if not isinstance(raw, str) or not raw.strip():
                raise RecipeError("invalid_path")
            values[key] = str(Path(raw).expanduser().resolve(strict=False))
    output = Path(str(values[ParameterKey.OUTPUT_FILE])) if ParameterKey.OUTPUT_FILE in values else None
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
    plan = ResolvedRunPlan(definition, snapshot, source, output, database,
                           output.with_name(output.stem + "_assets") if output else None)
    validate_plan_paths(plan)
    return plan


def validate_plan_paths(plan: ResolvedRunPlan, active_database: Path | None = None) -> None:
    targets = [p for p in (plan.database_file, plan.output_file, plan.assets_dir) if p is not None]
    for index, path in enumerate(targets):
        if any(paths_alias(path, other) for other in targets[index + 1:]):
            raise RecipeError("target_alias")
        writes_database = any(s.kind in {StepKind.PREPARE_DATABASE, StepKind.IMPORT_REPORTS}
                              for s in plan.definition.steps)
        if active_database is not None and paths_alias(path, active_database) and (
                path != plan.database_file or writes_database):
            raise RecipeError("active_database_alias")
        for key in (ParameterKey.SOURCE_FILE,):
            source = plan.value(key)
            if source and paths_alias(path, Path(str(source))):
                raise RecipeError("source_alias")
        if plan.input_folder is not None:
            if paths_alias(path, plan.input_folder):
                raise RecipeError("source_alias")
            # Targets inside the report folder can become future input candidates.
            try:
                path.resolve().relative_to(plan.input_folder.resolve())
            except ValueError:
                pass
            else:
                raise RecipeError("target_inside_input")


def new_output_copy(plan: ResolvedRunPlan) -> ResolvedRunPlan:
    if plan.output_file is None:
        raise RecipeError("missing_output")
    original = plan.output_file
    writes_database = any(s.kind in {StepKind.PREPARE_DATABASE, StepKind.IMPORT_REPORTS}
                          for s in plan.definition.steps)
    for index in range(1, 10001):
        output = original.with_name(f"{original.stem} ({index}){original.suffix}")
        database = output.with_suffix(".db") if writes_database else plan.database_file
        assets = output.with_name(output.stem + "_assets")
        family = [output, output.with_suffix(".html"), assets]
        if writes_database and database is not None:
            family.extend((database, Path(str(database) + "-wal"), Path(str(database) + "-shm")))
        if not any(p.exists() or p.is_symlink() for p in family):
            values = dict(plan.binding.values)
            values[ParameterKey.OUTPUT_FILE] = str(output)
            if writes_database:
                values[ParameterKey.DATABASE_FILE] = str(database)
            result = replace(plan, binding=replace(plan.binding, values=tuple(values.items())),
                             output_file=output, database_file=database, assets_dir=assets,
                             run_id=str(uuid4()))
            validate_plan_paths(result)
            return result
    raise RecipeError("copy_limit")

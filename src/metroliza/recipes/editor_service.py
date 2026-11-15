"""Pure editor state; every preview/run uses the same immutable resolution."""
from __future__ import annotations

from dataclasses import replace

from .bindings import resolve_plan
from .contracts import (
    DataKind, DerivationRule, ParameterKey, ParameterMode, ParameterSpec, ParameterType,
    PrivateValue, RecipeError, StepKind, StepSpec,
)
from .storage import RecipeStore, StoredRecipe, copy_recipe
from .validation import validate_binding, validate_definition


class RecipeEditorService:
    def __init__(self, stored: StoredRecipe):
        validate_binding(stored.definition, stored.binding)
        self.original = stored
        self.current = stored

    @property
    def modified(self) -> bool:
        return self.current != self.original

    def _replace(self, *, definition=None, binding=None) -> StoredRecipe:
        if self.current.definition.builtin:
            raise RecipeError("builtin_requires_copy")
        candidate = StoredRecipe(definition or self.current.definition, binding or self.current.binding)
        validate_binding(candidate.definition, candidate.binding)
        self.current = candidate
        return candidate

    def duplicate(self, name: str | None = None) -> StoredRecipe:
        self.current = copy_recipe(self.current.definition, self.current.binding,
                                  name=name or self.current.binding.name)
        return self.current

    def rename(self, name: str) -> StoredRecipe:
        return self._replace(binding=replace(self.current.binding, name=name))

    def set_value(self, key: ParameterKey, value: PrivateValue) -> StoredRecipe:
        values = dict(self.current.binding.values)
        values[key] = value
        return self._replace(binding=replace(self.current.binding, values=tuple(values.items())))

    def set_mode(self, key: ParameterKey, mode: ParameterMode) -> StoredRecipe:
        specs = []
        for spec in self.current.definition.parameters:
            if spec.key is key:
                if mode is ParameterMode.DERIVED and key is not ParameterKey.DATABASE_FILE:
                    raise RecipeError("unknown_derivation")
                spec = replace(spec, mode=mode, rule=(DerivationRule.DATABASE_FROM_OUTPUT
                    if mode is ParameterMode.DERIVED else None))
            specs.append(spec)
        return self._replace(definition=replace(self.current.definition, parameters=tuple(specs)))

    def reorder_steps(self, kinds: tuple[StepKind, ...]) -> StoredRecipe:
        original = {step.kind: step for step in self.current.definition.steps}
        if len(kinds) != len(original) or set(kinds) != set(original):
            raise RecipeError("step_set_changed")
        definition = replace(self.current.definition, steps=tuple(original[k] for k in kinds))
        validate_definition(definition)
        return self._replace(definition=definition)

    def configure_reports(self, *, dates: bool, grouping_columns: tuple[str, ...],
                          additional_html: bool) -> StoredRecipe:
        from metroliza.recipes.report_configuration_adapter import GROUPING_COLUMNS
        if any(column not in GROUPING_COLUMNS for column in grouping_columns):
            raise RecipeError("unsupported_grouping_rule")
        kinds = [s.kind for s in self.current.definition.steps]
        if not ({StepKind.IMPORT_REPORTS, StepKind.OPEN_DATABASE} & set(kinds)):
            raise RecipeError("not_reports_recipe")
        prefix = [s for s in self.current.definition.steps if s.kind in {
            StepKind.PREPARE_DATABASE, StepKind.IMPORT_REPORTS, StepKind.OPEN_DATABASE}]
        params = {p.key: p for p in self.current.definition.parameters}
        values = dict(self.current.binding.values)
        current = DataKind.DATABASE
        if dates:
            for key in (ParameterKey.DATE_FROM, ParameterKey.DATE_TO):
                params.setdefault(key, ParameterSpec(key, ParameterType.TEXT, ParameterMode.PROMPT, False))
                values.setdefault(key, "")
        else:
            for key in (ParameterKey.DATE_FROM, ParameterKey.DATE_TO):
                params.pop(key, None)
                values.pop(key, None)
        if dates or ParameterKey.FILTER_VALUES in params:
            prefix.append(StepSpec(StepKind.FILTER, current, DataKind.SELECTION))
            current = DataKind.SELECTION
        if grouping_columns:
            params[ParameterKey.GROUPING_RULES] = ParameterSpec(
                ParameterKey.GROUPING_RULES, ParameterType.STRINGS, ParameterMode.FIXED)
            values[ParameterKey.GROUPING_RULES] = grouping_columns
            prefix.append(StepSpec(StepKind.GROUP, current, DataKind.SELECTION))
            current = DataKind.SELECTION
        else:
            params.pop(ParameterKey.GROUPING_RULES, None)
            values.pop(ParameterKey.GROUPING_RULES, None)
        main = StepKind.EXPORT_MAIN in kinds
        if main:
            prefix.append(StepSpec(StepKind.EXPORT_MAIN, current, DataKind.ARTIFACT))
            current = DataKind.ARTIFACT
        if additional_html or not main:
            prefix.append(StepSpec(StepKind.EXPORT_HTML, current, DataKind.ARTIFACT))
        prefix.append(StepSpec(StepKind.VERIFY_OUTPUT, DataKind.ARTIFACT, DataKind.ARTIFACT))
        return self._replace(definition=replace(self.current.definition, steps=tuple(prefix),
            parameters=tuple(params.values())), binding=replace(self.current.binding, values=tuple(values.items())))

    def preview(self):
        return resolve_plan(self.current.definition, self.current.binding)

    def save(self, store: RecipeStore, *, as_new: bool = False) -> StoredRecipe:
        if as_new or self.current.definition.builtin:
            self.duplicate()
        saved = store.save(self.current.definition, self.current.binding,
            expected_revision=self.current.binding.revision or None)
        self.original = self.current = saved
        return saved

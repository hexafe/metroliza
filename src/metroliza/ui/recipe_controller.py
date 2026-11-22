"""One controller and one cooperatively stopped worker across all recipe views."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from metroliza.recipes.bindings import paths_alias, resolve_plan, validate_plan_paths
from metroliza.recipes.builtin_recipes import BUILTIN_RECIPES, builtin_binding
from metroliza.recipes.contracts import ParameterKey, RecipeError, StepKind
from metroliza.ui import detached_threads


class _RecipeTask(QThread):
    returned = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.returned.emit(self.operation())
        except RecipeError as exc:
            self.failed.emit(exc.code)
        except Exception:
            self.failed.emit("recipe_execution_failed")


class RecipeController(QObject):
    view_requested = pyqtSignal()
    changed = pyqtSignal(object)
    prepared = pyqtSignal(object)
    failed = pyqtSignal(str)
    event_received = pyqtSignal(object)
    selection_changed = pyqtSignal()
    idle = pyqtSignal()
    database_appended = pyqtSignal(object)

    def __init__(self, runner, parent=None, *, resolver=None, active_database=None,
                 source_directory=None, append_allowed=None):
        super().__init__(parent)
        self.runner = runner
        self.runner.on_event = self.event_received.emit
        self.event_received.connect(self._event)
        from metroliza.recipes.flow_diagnostics import RecipeFlowTrace
        self._flow_trace = RecipeFlowTrace()
        self.event_received.connect(self._flow_trace.observe)
        self.resolver = resolver
        self._active_database = active_database
        self._source_directory = source_directory
        self._append_allowed = append_allowed
        self.definition = None
        self.binding = None
        self._initial_binding = None
        self.draft_edited = False
        self.plan = None
        self.last_record = None
        self._task = None
        self._notified_append_run_id = None

    @property
    def busy(self):
        return bool(self._task is not None or (
            self.last_record is not None and self.last_record.ownership))

    def request_close(self):
        return not self.busy

    @property
    def can_repeat(self):
        return bool(not self.busy and self.plan is not None and self.last_record is not None
                    and self.last_record.run_id == self.plan.run_id)

    @property
    def append_in_progress(self):
        return self.busy and self.plan is not None and self.plan.appends_to_database

    def database_change_allowed(self, database_file) -> bool:
        """Veto only unsafe GUI context rebinds while a recipe still owns work."""
        if not self.busy or not database_file:
            return True
        plan = self.plan  # Includes admission before the worker acquires ownership.
        record = getattr(self.runner, "record", None)
        if record is not None and record.ownership:
            plan = getattr(self.runner, "plan", None) or plan
        if plan is None:
            return True
        try:
            if plan.appends_to_database and plan.database_file and paths_alias(plan.database_file, Path(database_file)):
                return False
            validate_plan_paths(plan, Path(database_file))
        except (ValueError, OSError):
            return False
        return True

    def _sync_active_database(self):
        if self._active_database is not None:
            value = self._active_database()
            self.runner.active_database = Path(value) if value else None

    def launch(self, definition, binding=None, *, start_over=False):
        self.view_requested.emit()
        if self.busy:
            return False
        self._sync_active_database()
        if isinstance(definition, str):
            found = next((d for d in BUILTIN_RECIPES if d.recipe_id == definition), None)
            if found is not None:
                definition = found
            elif self.resolver is not None:
                stored = self.resolver(definition)
                definition, binding = stored.definition, stored.binding
            else:
                self.failed.emit("recipe_not_found")
                return False
        if (not start_over and self.draft_edited and self.definition == definition
                and (binding is None or binding == self._initial_binding)):
            return True
        self.definition = definition
        if binding is None:
            source = self._source_directory() if self._source_directory is not None else None
            binding = builtin_binding(
                definition, str(source) if source and Path(source).is_dir() else "",
                existing_database=str(getattr(self.runner, "active_database", None) or ""),
            )
        self.draft_edited = False
        self._initial_binding = self.binding = binding
        self.plan = None
        self.selection_changed.emit()
        return True

    def restart(self):
        if self.definition is None or self.busy:
            return False
        binding = None if self.definition.builtin else self._initial_binding
        return self.launch(self.definition, binding, start_over=True)

    def prepare(self, values):
        if self.busy or self.definition is None:
            return False
        try:
            self._sync_active_database()
            merged = dict(self.binding.values)
            merged.update({ParameterKey(key): value for key, value in values.items()})
            binding = replace(self.binding, values=tuple(merged.items()))
            plan = resolve_plan(self.definition, binding)
            validate_plan_paths(plan, getattr(self.runner, "active_database", None))
            self.binding = binding
            self.plan = plan
        except RecipeError as exc:
            self.failed.emit(exc.code)
            return False
        self.prepared.emit(self.plan)
        return True

    def _submit(self, operation):
        if self._task is not None:
            self.view_requested.emit()
            return False
        task = _RecipeTask(operation, self)
        self._task = task
        task.returned.connect(self._returned)
        task.failed.connect(self.failed)
        task.finished.connect(self._finished)
        detached_threads.register(task, defer_quit=True)
        task.start()
        return True

    def start(self):
        if self.busy or self.plan is None:
            return False
        plan = self.plan
        try:
            self._sync_active_database()
            validate_plan_paths(plan, getattr(self.runner, "active_database", None))
            if plan.appends_to_database and self._append_allowed is not None:
                if not self._append_allowed(plan.database_file):
                    raise RecipeError("append_busy")
            token = self.runner.admit_start(plan)
        except RecipeError as exc:
            self.failed.emit(exc.code)
            return False
        try:
            submitted = self._submit(lambda: self.runner.start(plan, admission=token))
        except Exception:
            self.runner.withdraw_start(token)
            raise
        if submitted:
            self.draft_edited = False
        else:
            self.runner.withdraw_start(token)
        return submitted

    def resume(self, decision="continue"):
        if self._task is not None:
            return False
        try:
            self._sync_active_database()
            if decision != "new_copy":
                validate_plan_paths(self.runner.plan, getattr(self.runner, "active_database", None))
        except RecipeError as exc:
            self.failed.emit(exc.code)
            return False
        return self._submit(lambda: self.runner.resume(decision))

    def cancel(self):
        self.runner.cancel()
        # A paused run has no thread that can finish the cooperative cancel.
        if self._task is None:
            self.last_record = self.runner.record
            if self.last_record is not None:
                self.changed.emit(self.last_record)
            self.idle.emit()

    def repeat(self):
        if not self.can_repeat:
            return False
        self.plan = None
        self.selection_changed.emit()
        self.view_requested.emit()
        return True

    def _event(self, event):
        self.last_record = event.record
        self.changed.emit(event.record)

    def _returned(self, record):
        submitted_plan = self.plan
        self.plan = self.runner.plan
        self.last_record = record
        if self.plan is not None:
            self.definition = self.plan.definition
            self.binding = self.plan.binding
            if submitted_plan is None or submitted_plan.run_id != self.plan.run_id:
                self.selection_changed.emit()
            self.prepared.emit(self.plan)
        self.changed.emit(record)
        self._notify_database_append(record)

    def _notify_database_append(self, record):
        plan = self.plan
        if (plan is not None and plan.appends_to_database and record.run_id == plan.run_id
                and self._notified_append_run_id != record.run_id
                and any(step.kind is StepKind.IMPORT_REPORTS and step.result.imported_count
                        for step in record.steps)):
            self._notified_append_run_id = record.run_id
            self.database_appended.emit(plan.database_file)

    def _finished(self):
        task = self._task
        if task is not None:
            detached_threads.run_when_finished((task,), lambda: self._retire(task))

    def _retire(self, task):
        if self._task is not task:
            return
        self._task = None
        task.deleteLater()
        self.idle.emit()

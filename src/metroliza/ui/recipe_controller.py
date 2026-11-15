"""One controller and one cooperatively stopped worker across all recipe views."""
from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import BUILTIN_RECIPES, builtin_binding
from metroliza.recipes.contracts import ParameterKey, RecipeError
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

    def __init__(self, runner, parent=None, *, resolver=None):
        super().__init__(parent)
        self.runner = runner
        self.runner.on_event = self.event_received.emit
        self.event_received.connect(self._event)
        self.resolver = resolver
        self.definition = None
        self.binding = None
        self.plan = None
        self.last_record = None
        self._task = None

    @property
    def busy(self):
        return bool(self._task is not None or (
            self.last_record is not None and self.last_record.ownership))

    def request_close(self):
        return not self.busy

    def launch(self, definition, binding=None):
        self.view_requested.emit()
        if self.busy:
            return False
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
        self.definition = definition
        self.binding = binding or builtin_binding(definition)
        self.plan = None
        self.selection_changed.emit()
        return True

    def prepare(self, values):
        if self.busy or self.definition is None:
            return False
        try:
            merged = dict(self.binding.values)
            merged.update({ParameterKey(key): value for key, value in values.items()})
            binding = replace(self.binding, values=tuple(merged.items()))
            self.plan = resolve_plan(self.definition, binding)
            self.binding = binding
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
        return self._submit(lambda: self.runner.start(self.plan))

    def resume(self, decision="continue"):
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
        if self.busy or self.definition is None:
            return False
        self.plan = None
        self.selection_changed.emit()
        self.view_requested.emit()
        return True

    def _event(self, event):
        self.last_record = event.record
        self.changed.emit(event.record)

    def _returned(self, record):
        self.plan = self.runner.plan
        self.last_record = record
        self.changed.emit(record)

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

"""Lazy composition of the shared recipe workspace and existing service engines."""
from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from metroliza.ui.recipe_library_page import RecipeLibraryPage, RecipeQuickFlows


_FAVORITES_PREF = "presentation/recipes/favorites"


def open_capture_editor(parent, module, request, **configuration):
    """Find the existing main owner, retaining the source dialog's configuration."""
    owner = parent
    while owner is not None and not hasattr(owner, "_ensure_recipe_workspace"):
        owner = owner.parent()
    if owner is None:
        raise ValueError("recipe_workspace_unavailable")
    owner._ensure_recipe_workspace().capture(module, request, **configuration)
    owner._show_workspace_page("receptury")


class RecipeHome(RecipeQuickFlows):
    def __init__(self, parent):
        from metroliza.recipes.builtin_recipes import QUICK_REPORT_RECIPES
        from metroliza.recipes.storage import RecipeStore

        self.store = RecipeStore()
        defaults = [definition.recipe_id for definition in QUICK_REPORT_RECIPES]
        stored_ids = parent.ui_preferences.get(_FAVORITES_PREF, defaults, expected_type=list)
        self.favorite_ids = list(dict.fromkeys(identity for identity in stored_ids if isinstance(identity, str)))
        super().__init__(entries=self._saved_pins, parent=parent)
        self.set_favorites(self.favorite_ids)
        self.library_requested.connect(lambda: self.launch_requested.emit(""))

    def _saved_pins(self):
        from metroliza.recipes.builtin_recipes import BUILTIN_LABELS

        entries = []
        for identity in self.favorite_ids:
            if identity in BUILTIN_LABELS:
                continue
            try:
                entries.append(self.store.load(identity))
            except (ValueError, OSError):
                continue
        return entries


class RecipeWorkspace(QWidget):
    """One persistent controller survives page changes and repeated launch clicks."""
    analysis_completed = pyqtSignal(object)

    def __init__(self, main_window):
        super().__init__(main_window)
        from metroliza.recipes.runner import RecipeRunner
        from metroliza.ui.recipe_controller import RecipeController
        from metroliza.ui.recipe_ports import RecipePorts
        from metroliza.ui.recipe_runner_page import RecipeRunnerPage

        self.main_window = main_window
        self.store = main_window.recipe_home.store
        ports = RecipePorts()
        self.controller = RecipeController(RecipeRunner(ports), self, resolver=self.store.load,
            active_database=lambda: self.main_window.db_file,
            source_directory=lambda: self.main_window.directory,
            append_allowed=main_window._recipe_append_allowed)
        self.controller.database_appended.connect(main_window._on_recipe_database_appended)
        self._close_requested = False
        self._editors = []
        layout = QVBoxLayout(self)
        self.catalog_notice = QLabel()
        self.catalog_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.catalog_notice.setWordWrap(True)
        layout.addWidget(self.catalog_notice)
        self.stack = QStackedWidget()
        self.library = RecipeLibraryPage(self.controller, self.entries, self)
        self.run_page = RecipeRunnerPage(self.controller, self)
        back = QPushButton("Wszystkie receptury")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.library))
        layout.addWidget(back)
        layout.addWidget(self.stack)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.run_page)
        self.controller.view_requested.connect(lambda: self.stack.setCurrentWidget(self.run_page))
        self.controller.view_requested.connect(lambda: main_window._show_workspace_page("receptury"))
        self.controller.idle.connect(self._idle)
        self.library.copy_requested.connect(self.copy)
        self.library.edit_requested.connect(self.edit)
        self.quick = main_window.recipe_home
        self.library.set_favorites(self.quick.favorite_ids)
        self.library.favorites_changed.connect(self._favorites)
        self.quick.return_requested.connect(self.controller.view_requested)
        self.controller.event_received.connect(self._home_event)
        self.controller.changed.connect(self._home_result)

    def entries(self):
        from metroliza.recipes.builtin_recipes import BUILTIN_RECIPES, builtin_binding
        from metroliza.recipes.storage import StoredRecipe
        builtins = tuple(StoredRecipe(d, builtin_binding(d)) for d in BUILTIN_RECIPES)
        try:
            local, issues = self.store.scan()
        except (ValueError, OSError):
            self.catalog_notice.setText("Prywatna biblioteka wymaga sprawdzenia formatu lub dostępu do plików.")
            self.catalog_notice.setToolTip("")
            return builtins
        filenames = tuple(issue.filename + (" (nowszy format)" if issue.code == "newer_format" else "")
                          for issue in issues)
        self.catalog_notice.setToolTip("\n".join(filenames))
        shown = ", ".join(filenames[:5])
        if len(filenames) > 5:
            shown += f" i {len(filenames) - 5} więcej (zobacz podpowiedź)"
        self.catalog_notice.setText(f"Nie udało się odczytać receptur z plików {shown}." if shown else "")
        return builtins + local

    def launch(self, identity=""):
        if not identity:
            self._refresh_catalog()
            self.stack.setCurrentWidget(self.library)
            return
        try:
            self.controller.launch(identity)
        except (ValueError, OSError):
            self.controller.failed.emit("recipe_not_found")

    def _favorites(self, identities):
        ordered = list(identities)
        self.library.set_favorites(ordered)
        self.main_window.ui_preferences.set(_FAVORITES_PREF, ordered)
        self.quick.favorite_ids = ordered
        self.quick.set_favorites(ordered)

    def _home_event(self, event):
        from metroliza.recipes.run_state import RunState
        from metroliza.ui.recipe_labels import STEP_LABELS
        from metroliza.ui.recipe_runner_page import _PHASE_LABELS, _STATE_LABELS

        if not event.record.ownership or self.controller.plan is None:
            self.quick.set_active()
            return
        stage = _STATE_LABELS[event.record.state]
        if event.record.state is RunState.RUNNING:
            stage = STEP_LABELS.get(event.step_kind) or _PHASE_LABELS.get(event.phase) or "Przygotowanie"
        self.quick.set_active(self.controller.plan.binding.name, stage)

    def _home_result(self, record):
        from metroliza.recipes.contracts import ParameterKey

        plan = self.controller.plan
        paths = self.quick.set_result(plan, record)
        if paths:
            sources = plan.value(ParameterKey.SOURCE_FILES, ())
            source = (sources[0] if len(sources) == 1 else None) if sources else (
                plan.value(ParameterKey.SOURCE_FILE) or plan.input_folder or plan.database_file)
            settings = {"recipe": plan.binding.name}
            settings.update((key.value, plan.value(key)) for key in (ParameterKey.DATE_FROM, ParameterKey.DATE_TO)
                            if plan.value(key))
            assets = []
            if any(path.suffix.lower() in {".html", ".htm"} for path in paths):
                assets = list(dict.fromkeys(step.result.dashboard_assets_path for step in record.steps
                              if step.result.artifact_verified and step.result.dashboard_assets_path))
            self.analysis_completed.emit({"kind": "recipe", "artifacts": [str(path) for path in paths],
                                          "source": str(source) if source else None, "settings": settings, "assets": assets})

    def database_change_allowed(self, database_file):
        return self.controller.database_change_allowed(database_file)

    def request_close(self):
        if any(editor.close() is False for editor in tuple(self._editors)):
            return False
        if self.controller.request_close():
            return True
        self._close_requested = True
        self.controller.cancel()
        return False

    def _idle(self):
        if self._close_requested and self.controller.request_close():
            self._close_requested = False
            QTimer.singleShot(0, self.main_window.close)

    def copy(self, stored):
        from metroliza.recipes.storage import copy_recipe
        copied = copy_recipe(stored.definition, stored.binding, name=stored.binding.name + " — kopia")
        self.edit(copied)

    def edit(self, stored):
        from metroliza.ui.recipe_editor import RecipeEditor
        editor = RecipeEditor(stored, self.store, self)
        self._editors.append(editor)
        editor.saved.connect(lambda saved: self._recipe_saved(editor, saved))
        editor.finished.connect(self._refresh_catalog)
        editor.finished.connect(lambda _result: self._editors.remove(editor))
        editor.open()

    def _refresh_catalog(self, *_args):
        self.library.refresh()
        self.quick.set_favorites(self.library.favorite_order)

    def _recipe_saved(self, editor, stored):
        identity = stored.definition.recipe_id
        ordered = self.library.favorite_order
        if editor.pin_on_save.isChecked() and identity not in ordered:
            self._favorites([*ordered, identity])
        self._refresh_catalog()

    def capture(self, module, request, **configuration):
        try:
            if module == "reports":
                from metroliza.recipes.report_configuration_adapter import capture_export_configuration
                stored = capture_export_configuration(request, **configuration)
            elif module == "tabular":
                from metroliza.recipes.tabular_adapter import capture
                stored = capture(request)
            else:
                from metroliza.recipes.industrial_adapter import capture
                stored = capture(request)
            self.edit(stored)
        except ValueError:
            QMessageBox.warning(self, "Recipe", "This configuration requires a supported field or group rule before it can be saved.")

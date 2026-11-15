"""Lazy composition of the shared recipe workspace and existing service engines."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)


def open_capture_editor(parent, module, request, **configuration):
    """Find the existing main owner, retaining the source dialog's configuration."""
    owner = parent
    while owner is not None and not hasattr(owner, "_ensure_recipe_workspace"):
        owner = owner.parent()
    if owner is None:
        raise ValueError("recipe_workspace_unavailable")
    owner._ensure_recipe_workspace().capture(module, request, **configuration)
    owner._show_workspace_page("receptury")


class RecipeHome(QWidget):
    launch_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(QLabel("Szybkie flow"))
        row = QHBoxLayout()
        for identity, label in (("reports_excel_main", "Raporty → Excel Main"),
                                ("reports_dashboard_html", "Raporty → Dashboard HTML"),
                                ("", "Wszystkie receptury")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, selected=identity: self.launch_requested.emit(selected))
            row.addWidget(button)
        self.layout.addLayout(row)
        favorites = parent.ui_preferences.get("presentation/recipes/favorites", [], expected_type=list)
        if favorites:
            from metroliza.recipes.storage import RecipeStore
            self.layout.addWidget(QLabel("Ulubione"))
            try:
                for stored in RecipeStore().list():
                    if stored.definition.recipe_id in favorites:
                        button = QPushButton(stored.binding.name)
                        button.clicked.connect(lambda _checked=False, identity=stored.definition.recipe_id:
                                               self.launch_requested.emit(identity))
                        self.layout.addWidget(button)
            except (ValueError, OSError):
                self.layout.addWidget(QLabel("Sprawdź prywatną bibliotekę receptur."))
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.layout.addWidget(self.summary)


class _RecipePorts:
    def __init__(self, reports, analytics):
        self.reports, self.analytics = reports, analytics

    def _for(self, plan):
        from metroliza.recipes.contracts import StepKind
        return self.analytics if any(
            step.kind in (StepKind.LOAD_TABULAR, StepKind.LOAD_INDUSTRIAL)
            for step in plan.definition.steps
        ) else self.reports

    def preflight(self, plan, context):
        return self._for(plan).preflight(plan, context)

    def approve(self, plan, decision):
        return self._for(plan).approve(plan, decision)

    def execute(self, step, plan, context):
        return self._for(plan).execute(step, plan, context)

    def cancel(self):
        self.reports.cancel()
        self.analytics.cancel()

    def finish(self, plan):
        finish = getattr(self._for(plan), "finish", None)
        if finish is not None:
            finish(plan)


class RecipeWorkspace(QWidget):
    """One persistent controller survives page changes and repeated launch clicks."""
    def __init__(self, main_window):
        super().__init__(main_window)
        from metroliza.recipes.report_ports import ReportsRecipeService
        from metroliza.recipes.runner import RecipeRunner
        from metroliza.recipes.storage import RecipeStore
        from metroliza.ui.recipe_controller import RecipeController
        from metroliza.ui.recipe_execution_adapter import RecipeExecutionAdapter
        from metroliza.ui.recipe_library_page import RecipeLibraryPage, RecipeQuickFlows
        from metroliza.ui.recipe_runner_page import RecipeRunnerPage
        from metroliza.recipes.tabular_adapter import create_adapter_ports

        self.main_window = main_window
        self.store = RecipeStore()
        ports = _RecipePorts(
            ReportsRecipeService(RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export")),
            create_adapter_ports(),
        )
        self.controller = RecipeController(RecipeRunner(ports), self, resolver=self.store.load)
        self._close_requested = False
        self._editors = []
        layout = QVBoxLayout(self)
        self.catalog_notice = QLabel()
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
        self.controller.changed.connect(self._changed)
        self.controller.idle.connect(self._idle)
        self.library.copy_requested.connect(self.copy)
        self.library.edit_requested.connect(self.edit)
        self.quick = RecipeQuickFlows(self.controller, self.entries, main_window.recipe_home)
        self.quick.library_requested.connect(lambda: main_window._launch_recipe())
        favorites = main_window.ui_preferences.get("presentation/recipes/favorites", [], expected_type=list)
        self.library.favorites = set(favorites)
        self.quick.set_favorites(favorites)
        self.library.favorites_changed.connect(self._favorites)
        home_layout = main_window.recipe_home.layout
        for index in range(home_layout.count()):
            item = home_layout.itemAt(index)
            if item.widget() is not None:
                item.widget().hide()
            elif item.layout() is not None:
                for child in range(item.layout().count()):
                    item.layout().itemAt(child).widget().hide()
        home_layout.insertWidget(0, self.quick)

    def entries(self):
        from metroliza.recipes.builtin_recipes import BUILTIN_RECIPES, builtin_binding
        from metroliza.recipes.storage import StoredRecipe
        builtins = tuple(StoredRecipe(d, builtin_binding(d)) for d in BUILTIN_RECIPES)
        try:
            local = self.store.list()
        except (ValueError, OSError):
            self.catalog_notice.setText("Prywatna biblioteka wymaga sprawdzenia formatu lub dostępu do plików.")
            return builtins
        self.catalog_notice.clear()
        return builtins + local

    def launch(self, identity=""):
        if not identity:
            self.stack.setCurrentWidget(self.library)
            return
        self.controller.runner.active_database = (
            Path(self.main_window.db_file)
            if self.main_window.db_file else None
        )
        self.controller.launch(identity)

    def _changed(self, record):
        self.main_window.recipe_home.summary.setText("Flow: " + record.state.value)

    def _favorites(self, identities):
        self.quick.set_favorites(identities)
        self.main_window.ui_preferences.set("presentation/recipes/favorites", sorted(identities))

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
        editor.saved.connect(lambda _stored: self.library.refresh())
        editor.finished.connect(lambda _result: self.library.refresh())
        editor.finished.connect(lambda _result: self._editors.remove(editor))
        editor.open()

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

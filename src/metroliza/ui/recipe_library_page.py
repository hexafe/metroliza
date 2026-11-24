"""Compact recipe catalogue and Home shortcuts, sharing one run controller."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget,
)

from metroliza.recipes.builtin_recipes import BUILTIN_LABELS, QUICK_REPORT_RECIPES
from metroliza.recipes.contracts import StepKind


def recipe_module(definition):
    if any(s.kind is StepKind.LOAD_INDUSTRIAL for s in definition.steps):
        return "industrial"
    return "tabular" if any(s.kind is StepKind.LOAD_TABULAR for s in definition.steps) else "reports"


class RecipeLibraryPage(QWidget):
    copy_requested = pyqtSignal(object)
    edit_requested = pyqtSignal(object)
    favorites_changed = pyqtSignal(object)

    def __init__(self, controller, entries, parent=None, *, available=None):
        super().__init__(parent)
        self.controller = controller
        self.entries = entries
        def supported(definition):
            from metroliza.recipes.validation import validate_definition
            from metroliza.recipes.contracts import RecipeError
            try:
                validate_definition(definition)
                return True
            except RecipeError:
                return False
        self.available = available or supported
        self.favorites = set()
        self.favorite_order = []
        self._shown = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Receptury"))
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj receptury")
        self.search.setAccessibleName("Szukaj receptury")
        self.module = QComboBox()
        for label, value in (("Wszystkie moduły", ""), ("Reports", "reports"), ("Tabular", "tabular"), ("Industrial", "industrial")):
            self.module.addItem(label, value)
        controls.addWidget(self.search)
        controls.addWidget(self.module)
        refresh = QPushButton("Odśwież listę")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.list = QListWidget()
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self.run_button = QPushButton("Uruchom")
        self.copy_button = QPushButton("Utwórz kopię")
        self.edit_button = QPushButton("Edytuj")
        self.favorite_button = QPushButton("Ulubione ☆")
        self.move_up_button = QPushButton("Przenieś wyżej")
        self.move_down_button = QPushButton("Przenieś niżej")
        self.move_up_button.setAccessibleName("Przenieś ulubioną recepturę wyżej na Home")
        self.move_down_button.setAccessibleName("Przenieś ulubioną recepturę niżej na Home")
        for button in (self.run_button, self.copy_button, self.edit_button, self.favorite_button,
                       self.move_up_button, self.move_down_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.search.textChanged.connect(self.refresh)
        self.module.currentIndexChanged.connect(self.refresh)
        self.list.currentRowChanged.connect(self._selection)
        self.list.itemDoubleClicked.connect(lambda _item: self._run())
        self.list.installEventFilter(self)
        self.run_button.clicked.connect(self._run)
        self.copy_button.clicked.connect(lambda: self._emit(self.copy_requested))
        self.edit_button.clicked.connect(lambda: self._emit(self.edit_requested))
        self.favorite_button.clicked.connect(self._favorite)
        self.move_up_button.clicked.connect(lambda: self._move_favorite(-1))
        self.move_down_button.clicked.connect(lambda: self._move_favorite(1))
        self.refresh()

    def set_entries(self, entries):
        self.entries = entries
        self.refresh()

    def set_favorites(self, identities):
        self.favorite_order = list(identities)
        self.favorites = set(identities)
        self._selection()

    def refresh(self, *_):
        self.list.clear()
        self._shown = []
        entries = self.entries() if callable(self.entries) else self.entries
        query = self.search.text().casefold()
        module = self.module.currentData()
        for entry in entries:
            label = entry.binding.name
            if query not in label.casefold() or (module and recipe_module(entry.definition) != module):
                continue
            self._shown.append(entry)
            available = self.available(entry.definition)
            self.list.addItem(label + (" · wbudowana" if entry.definition.builtin else "")
                              + (" · adapter niedostępny" if not available else ""))
        self._selection()

    def selected(self):
        index = self.list.currentRow()
        return self._shown[index] if 0 <= index < len(self._shown) else None

    def _selection(self, *_):
        entry = self.selected()
        self.run_button.setEnabled(entry is not None and self.available(entry.definition))
        self.copy_button.setEnabled(entry is not None)
        self.edit_button.setEnabled(entry is not None and not entry.definition.builtin)
        self.favorite_button.setEnabled(entry is not None)
        self.favorite_button.setText("Ulubione ★" if entry and entry.definition.recipe_id in self.favorites else "Ulubione ☆")
        ordered = self.favorite_order
        position = ordered.index(entry.definition.recipe_id) if entry and entry.definition.recipe_id in ordered else -1
        self.move_up_button.setEnabled(position > 0)
        self.move_down_button.setEnabled(position >= 0 and position < len(ordered) - 1)

    def _move_favorite(self, delta):
        entry = self.selected()
        if entry is None:
            return
        identity = entry.definition.recipe_id
        ordered = list(self.favorite_order)
        if identity not in ordered:
            return
        position = ordered.index(identity)
        target = position + delta
        if not 0 <= target < len(ordered):
            return
        ordered[position], ordered[target] = ordered[target], ordered[position]
        self.favorites = set(ordered)
        self.favorite_order = ordered
        self.favorites_changed.emit(tuple(ordered))
        self._selection()

    def eventFilter(self, watched, event):
        if (watched is self.list and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._run()
            return True
        return super().eventFilter(watched, event)

    def _run(self):
        entry = self.selected()
        if entry and self.available(entry.definition):
            if entry.definition.builtin:
                self.controller.launch(entry.definition.recipe_id)
            else:
                self.controller.launch(entry.definition, entry.binding)

    def _emit(self, signal):
        entry = self.selected()
        if entry is not None:
            signal.emit(entry)

    def _favorite(self):
        entry = self.selected()
        if entry is None:
            return
        identity = entry.definition.recipe_id
        if identity in self.favorites:
            self.favorites.remove(identity)
            self.favorite_order.remove(identity)
        else:
            self.favorites.add(identity)
            self.favorite_order.append(identity)
        self.favorites_changed.emit(tuple(self.favorite_order))
        self._selection()


class RecipeQuickFlows(QWidget):
    """The same Home controls before and after the recipe workspace is created."""
    library_requested = pyqtSignal()
    launch_requested = pyqtSignal(str)
    return_requested = pyqtSignal()

    def __init__(self, controller=None, entries=(), parent=None):
        super().__init__(parent)
        self.controller = controller
        self.entries = entries
        self._result_run_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Przypięte receptury"))
        self.favorite_buttons = QGridLayout()
        layout.addLayout(self.favorite_buttons)
        self.empty_hint = QLabel("Przypnij recepturę w bibliotece, aby otwierać ją z Home.")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)
        all_recipes = QPushButton("Wszystkie receptury")
        all_recipes.clicked.connect(self.library_requested)
        layout.addWidget(all_recipes)

        self.active_label = QLabel()
        self.active_label.setTextFormat(Qt.TextFormat.PlainText)
        self.active_label.setWordWrap(True)
        self.active = QPushButton("Wróć do zadania")
        self.active.clicked.connect(self.return_requested)
        layout.addWidget(self.active_label)
        layout.addWidget(self.active)
        self.active_label.hide()
        self.active.hide()

        self.result = QLabel()
        self.result.setTextFormat(Qt.TextFormat.PlainText)
        self.result.setWordWrap(True)
        self.result.hide()
        layout.addWidget(self.result)
        self.result_actions = QHBoxLayout()
        layout.addLayout(self.result_actions)
        self.set_favorites(definition.recipe_id for definition in QUICK_REPORT_RECIPES)

    def set_favorites(self, identities):
        ids = tuple(dict.fromkeys(identity for identity in identities if isinstance(identity, str)))
        while self.favorite_buttons.count():
            button = self.favorite_buttons.takeAt(0).widget()
            button.hide()
            button.deleteLater()
        labels = dict(BUILTIN_LABELS)
        if any(identity not in labels for identity in ids):
            entries = self.entries() if callable(self.entries) else self.entries
            labels.update({entry.definition.recipe_id: entry.binding.name for entry in entries})
        for position, identity in enumerate(identity for identity in ids if identity in labels):
            button = QPushButton(labels[identity])
            button.clicked.connect(lambda _checked=False, selected=identity: self._launch_favorite(selected))
            self.favorite_buttons.addWidget(button, position // 2, position % 2)
        self.empty_hint.setVisible(not self.favorite_buttons.count())

    def _launch_favorite(self, identity):
        if self.controller is None:
            self.launch_requested.emit(identity)
            return
        try:
            self.controller.launch(identity)
        except (ValueError, OSError):
            self.controller.failed.emit("recipe_not_found")

    def set_active(self, name="", stage=""):
        if name and stage:
            self.active_label.setText(f"{name} · {stage}")
        self.active_label.setVisible(bool(name and stage))
        self.active.setVisible(bool(name and stage))

    def set_result(self, plan, record):
        from metroliza.recipes.ports import ResultCode
        from metroliza.recipes.run_state import RunState
        from metroliza.ui.result_actions import add_result_actions, existing_result_files

        if (plan is None or plan.run_id != record.run_id or self._result_run_id == record.run_id
                or record.state not in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS, RunState.PARTIAL}):
            return
        verified = {step.kind for step in record.steps if step.result.artifact_verified}
        paths = existing_result_files(self._result_paths(plan, verified))
        if record.code is ResultCode.WORKBOOK_NOT_PUBLISHED:
            paths = tuple(path for path in paths if path.suffix.lower() != ".xlsx")
        if not paths:
            return
        self._result_run_id = record.run_id
        while self.result_actions.count():
            button = self.result_actions.takeAt(0).widget()
            button.hide()
            button.deleteLater()
        self.result.setText(f"Ostatni wynik · {plan.binding.name}")
        self.result.show()

        def add_button(label):
            button = QPushButton(label)
            self.result_actions.addWidget(button)
            return button

        add_result_actions(self.window(), paths, add_button,
                           labels=("Otwórz Excel", "Otwórz HTML", "Pokaż w folderze"))
        return paths

    @staticmethod
    def _result_paths(plan, verified):
        output = plan.output_file
        if output is None:
            return ()
        if StepKind.ANALYZE_TABULAR in verified or (
                StepKind.VERIFY_OUTPUT in verified
                and any(step.kind is StepKind.ANALYZE_TABULAR for step in plan.definition.steps)):
            from metroliza.recipes.tabular_adapter import analytics_output_family

            outputs = analytics_output_family(plan.binding, output)
            return (outputs.dashboard, outputs.workbook) if outputs.workbook else (outputs.dashboard,)
        paths = []
        for step in plan.definition.steps:
            if step.kind not in verified and StepKind.VERIFY_OUTPUT not in verified:
                continue
            if step.kind is StepKind.EXPORT_MAIN:
                paths.append(output)
            elif step.kind is StepKind.EXPORT_HTML:
                paths.append(output.with_suffix(".html"))
        return tuple(paths)

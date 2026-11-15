"""Compact recipe catalogue and Home shortcuts, sharing one run controller."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget,
)

from metroliza.recipes.builtin_recipes import BUILTIN_LABELS
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
        layout.addLayout(controls)
        self.list = QListWidget()
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self.run_button = QPushButton("Uruchom")
        self.copy_button = QPushButton("Utwórz kopię")
        self.edit_button = QPushButton("Edytuj")
        self.favorite_button = QPushButton("Ulubione ☆")
        for button in (self.run_button, self.copy_button, self.edit_button, self.favorite_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.search.textChanged.connect(self.refresh)
        self.module.currentIndexChanged.connect(self.refresh)
        self.list.currentRowChanged.connect(self._selection)
        self.list.itemDoubleClicked.connect(lambda _item: self._run())
        self.run_button.clicked.connect(self._run)
        self.copy_button.clicked.connect(lambda: self._emit(self.copy_requested))
        self.edit_button.clicked.connect(lambda: self._emit(self.edit_requested))
        self.favorite_button.clicked.connect(self._favorite)
        self.refresh()

    def set_entries(self, entries):
        self.entries = entries
        self.refresh()

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

    def _run(self):
        entry = self.selected()
        if entry and self.available(entry.definition):
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
        else:
            self.favorites.add(identity)
        self.favorites_changed.emit(frozenset(self.favorites))
        self._selection()


class RecipeQuickFlows(QWidget):
    library_requested = pyqtSignal()

    def __init__(self, controller, entries, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.entries = entries
        self.favorites = set()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Szybkie flow"))
        cards = QHBoxLayout()
        for identity, label in BUILTIN_LABELS.items():
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, recipe_id=identity: controller.launch(recipe_id))
            cards.addWidget(button)
        layout.addLayout(cards)
        self.favorite_buttons = QHBoxLayout()
        layout.addLayout(self.favorite_buttons)
        all_recipes = QPushButton("Wszystkie receptury")
        all_recipes.clicked.connect(self.library_requested)
        layout.addWidget(all_recipes)
        self.active = QPushButton("Brak aktywnego zadania")
        self.active.clicked.connect(controller.view_requested)
        self.active.setEnabled(False)
        layout.addWidget(self.active)
        controller.changed.connect(self._changed)

    def set_favorites(self, identities):
        self.favorites = set(identities)
        while self.favorite_buttons.count():
            self.favorite_buttons.takeAt(0).widget().deleteLater()
        entries = self.entries() if callable(self.entries) else self.entries
        for entry in entries:
            if entry.definition.recipe_id in self.favorites:
                button = QPushButton(entry.binding.name)
                button.clicked.connect(lambda _checked=False, item=entry:
                                       self.controller.launch(item.definition, item.binding))
                self.favorite_buttons.addWidget(button)

    def _changed(self, record):
        from metroliza.ui.recipe_runner_page import _STATE_LABELS
        self.active.setText("Zadanie: " + _STATE_LABELS.get(record.state, record.state.value))
        self.active.setEnabled(True)

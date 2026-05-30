"""Grouping dialog for cached Oznak industrial production-line data."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from metroliza.industrial.industrial_workflow_state import (
    INDUSTRIAL_GROUPING_ALLOWED_FIELDS,
    INDUSTRIAL_GROUPING_FIELDS,
    IndustrialGroupingState,
)
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size, status_chip


class IndustrialGroupingDialog(QDialog):
    """Choose production-line fields used for industrial export summaries and charts."""

    def __init__(self, parent=None, state: IndustrialGroupingState | None = None):
        super().__init__(parent)
        self.state = state or IndustrialGroupingState()
        self.setWindowTitle("Industrial data grouping")
        configure_window_size(self, minimum=(460, 360), initial=(560, 520))

        self.summary_label = status_chip(self.state.summary(), "neutral")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search fields...")
        self.field_list = QListWidget()
        self.field_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        self.clear_button = QPushButton("Clear grouping")
        self.apply_button = QPushButton("Use grouping")
        self.cancel_button = QPushButton("Cancel")

        self.search_input.textChanged.connect(self.filter_fields)
        self.clear_button.clicked.connect(self.clear_grouping)
        self.apply_button.clicked.connect(self.apply_grouping)
        self.cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.summary_label)
        layout.addWidget(QLabel("Fields"))
        layout.addWidget(self.search_input)
        layout.addWidget(self.field_list, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)

        self.populate_fields()
        apply_metroliza_theme(self)

    def populate_fields(self) -> None:
        self.field_list.clear()
        selected = set(self.state.fields)
        for field_name, label in INDUSTRIAL_GROUPING_FIELDS:
            item = QListWidgetItem(label)
            item.setData(32, field_name)
            self.field_list.addItem(item)
            if field_name in selected:
                item.setSelected(True)

    def filter_fields(self) -> None:
        search = self.search_input.text().strip().lower()
        for index in range(self.field_list.count()):
            item = self.field_list.item(index)
            item.setHidden(bool(search) and search not in item.text().lower())

    def current_state(self) -> IndustrialGroupingState:
        fields: list[str] = []
        for item in self.field_list.selectedItems():
            field_name = item.data(32)
            if field_name in INDUSTRIAL_GROUPING_ALLOWED_FIELDS:
                fields.append(str(field_name))
        ordered = tuple(field for field, _label in INDUSTRIAL_GROUPING_FIELDS if field in set(fields))
        return IndustrialGroupingState(fields=ordered)

    def clear_grouping(self) -> None:
        self.field_list.clearSelection()
        state = IndustrialGroupingState()
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_grouping_state"):
            parent.set_industrial_grouping_state(state)
        self.state = state
        self.summary_label.setText(state.summary())
        self.accept()

    def apply_grouping(self) -> None:
        state = self.current_state()
        state.validated_fields()
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_grouping_state"):
            parent.set_industrial_grouping_state(state)
        self.state = state
        self.accept()

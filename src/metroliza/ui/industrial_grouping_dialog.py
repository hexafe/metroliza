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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from metroliza.industrial.industrial_workflow_state import (
    INDUSTRIAL_GROUPING_ALLOWED_FIELDS,
    INDUSTRIAL_GROUPING_FIELDS,
    IndustrialGroupingState,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    secondary_label,
    set_status_variant,
    status_chip,
)


class IndustrialGroupingDialog(QDialog):
    """Choose production-line fields used for industrial export summaries and charts."""

    def __init__(self, parent=None, state: IndustrialGroupingState | None = None):
        super().__init__(parent)
        self.state = state or IndustrialGroupingState()
        self._committed_state = self.state
        self._discard_gate_active = False
        self.setWindowTitle("Industrial data grouping")
        configure_window_size(self, minimum=(460, 360), initial=(560, 520))

        self.summary_label = status_chip(self.state.summary(), "neutral")
        configure_accessibility(
            self.summary_label,
            name="Industrial grouping draft summary",
            description="Summarizes the group fields selected in the uncommitted draft.",
        )
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search fields...")
        self.field_list = QListWidget()
        self.field_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        self.clear_button = QPushButton("Reset grouping")
        self.apply_button = QPushButton("Use grouping")
        self.cancel_button = QPushButton("Cancel")

        self.search_input.textChanged.connect(self.filter_fields)
        self.field_list.itemSelectionChanged.connect(self._sync_draft_state)
        self.clear_button.clicked.connect(self._request_reset_grouping)
        self.apply_button.clicked.connect(self.apply_grouping)
        self.cancel_button.clicked.connect(self._request_cancel)
        configure_dialog_button_roles(
            primary=self.apply_button,
            secondary=(self.cancel_button,),
            quiet=(self.clear_button,),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(self.summary_label)
        context_label = secondary_label(
            "Scope: cached industrial export summaries and charts. Changes stay in this draft "
            "until you use the grouping."
        )
        configure_accessibility(context_label, name="Industrial grouping scope")
        layout.addWidget(context_label)
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
        self._sync_draft_state()
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

    def _is_dirty(self) -> bool:
        return self.current_state() != self._committed_state

    def _sync_draft_state(self) -> None:
        state = self.current_state()
        count = len(state.fields)
        noun = "field" if count == 1 else "fields"
        total = len(INDUSTRIAL_GROUPING_FIELDS)
        self.summary_label.setText(
            f"{count} group {noun} selected from {total} available. {state.summary()}"
        )
        set_status_variant(self.summary_label, "success" if count else "neutral")

    def _request_reset_grouping(self) -> None:
        current = self.current_state()
        if self._is_dirty() and current != IndustrialGroupingState():
            if not self._confirm_discard(
                "Reset grouping draft?",
                "Resetting will discard the grouping changes you have not applied.",
            ):
                return
        self.clear_grouping()

    def _request_cancel(self) -> None:
        self.reject()

    def _discard_draft_if_allowed(self) -> bool:
        if self._discard_gate_active:
            return False
        if not self._is_dirty():
            return True
        if self.isVisible():
            self._discard_gate_active = True
            try:
                allowed = self._confirm_discard(
                    "Discard grouping changes?",
                    "Canceling will discard the grouping changes you have not applied.",
                )
            finally:
                self._discard_gate_active = False
            if not allowed:
                return False
        self._restore_committed_state()
        return True

    def reject(self) -> None:
        if not self._discard_draft_if_allowed():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if not self._discard_draft_if_allowed():
            event.ignore()
            return
        super().closeEvent(event)

    def _restore_committed_state(self) -> None:
        selected = set(self._committed_state.fields)
        self.field_list.blockSignals(True)
        try:
            for index in range(self.field_list.count()):
                item = self.field_list.item(index)
                item.setSelected(item.data(32) in selected)
        finally:
            self.field_list.blockSignals(False)
        self._sync_draft_state()

    def _confirm_discard(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def apply_grouping(self) -> None:
        state = self.current_state()
        state.validated_fields()
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_grouping_state"):
            parent.set_industrial_grouping_state(state)
        self.state = state
        self._committed_state = state
        self.accept()

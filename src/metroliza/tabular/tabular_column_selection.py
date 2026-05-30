"""Shared column-list mechanics for CSV/Excel filter and grouping dialogs."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget


def column_matches_search(column: str, label: str, search_text: str) -> bool:
    """Return whether a column or display label matches the search text."""

    search = str(search_text or "").strip().casefold()
    if not search:
        return True
    return search in str(label or "").casefold() or search in str(column or "").casefold()


def current_column_from_list(list_widget: QListWidget) -> str | None:
    """Return the column key attached to the current list item."""

    item = list_widget.currentItem()
    if item is None:
        return None
    column = item.data(Qt.ItemDataRole.UserRole)
    return str(column) if column is not None else None


def populate_column_list(
    list_widget: QListWidget,
    columns: Iterable[str],
    *,
    label_for: Callable[[str], str],
    search_text: str = "",
    current_column: str | None = None,
    fallback: str = "first",
    block_signals: bool = False,
) -> None:
    """Populate a QListWidget with filtered column items and preserve selection."""

    previous_block_state = list_widget.blockSignals(True) if block_signals else None
    try:
        list_widget.clear()
        current_item = None
        for column in columns:
            key = str(column)
            label = str(label_for(key))
            if not column_matches_search(key, label, search_text):
                continue
            list_widget.addItem(label)
            item = list_widget.item(list_widget.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, key)
            if key == current_column:
                current_item = item

        if current_item is not None:
            current_item.setSelected(True)
            list_widget.setCurrentItem(current_item)
        elif list_widget.currentItem() is None and list_widget.count():
            row = list_widget.count() - 1 if fallback == "last" else 0
            list_widget.setCurrentRow(row)
    finally:
        if block_signals:
            list_widget.blockSignals(bool(previous_block_state))


def set_current_column(list_widget: QListWidget, column: str) -> None:
    """Select the first item whose user data matches the provided column key."""

    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == column:
            list_widget.setCurrentItem(item)
            return


def column_sequence_text(columns: Iterable[str], *, label_for: Callable[[str], str]) -> str:
    """Return a compact, user-facing representation of selected columns."""

    return " | ".join(str(label_for(str(column))) for column in columns)

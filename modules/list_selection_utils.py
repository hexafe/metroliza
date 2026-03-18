"""Shared list-widget selection and filtering helpers for dialogs."""

from collections.abc import Callable

from PyQt6.QtCore import Qt
import PyQt6.QtWidgets as QtWidgets


class ListSelectionUtils:
    """Provide shared shift-range and search filtering list widget behavior."""

    def __init__(self, keyboard_modifiers: Callable[[], int] | None = None):
        self._last_clicked_row_by_list = {}
        self._keyboard_modifiers = keyboard_modifiers or self._default_keyboard_modifiers

    @staticmethod
    def _default_keyboard_modifiers():
        app_cls = getattr(QtWidgets, "QApplication", None)
        if app_cls is None or not hasattr(app_cls, "keyboardModifiers"):
            return 0
        return app_cls.keyboardModifiers()

    def connect_shift_range_behavior(self, list_widget):
        list_widget.itemPressed.connect(lambda item, lw=list_widget: self.handle_shift_range_press(lw, item))

    def handle_shift_range_press(self, list_widget, item):
        if item is None:
            return

        row = list_widget.row(item)
        previous_row = self._last_clicked_row_by_list.get(list_widget)
        is_shift_pressed = bool(self._keyboard_modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if is_shift_pressed and previous_row is not None:
            start_row = min(previous_row, row)
            end_row = max(previous_row, row)
            visible_items = [
                list_widget.item(index)
                for index in range(start_row, end_row + 1)
                if list_widget.item(index) is not None and not list_widget.item(index).isHidden()
            ]
            should_select = any(not list_item.isSelected() for list_item in visible_items)
            for list_item in visible_items:
                list_item.setSelected(should_select)
            list_widget.setCurrentItem(item)
            return

        self._last_clicked_row_by_list[list_widget] = row

    def preserve_selection_during_filter(self, list_widget, search_text, canonical_text_getter=None):
        selected_items = list_widget.selectedItems()
        list_widget.clearSelection()

        normalized_search_text = str(search_text or "").lower()

        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if not normalized_search_text:
                item.setHidden(False)
                continue

            item_text = item.text().lower()
            canonical_text = ""
            if callable(canonical_text_getter):
                canonical_text = str(canonical_text_getter(item) or "").lower()

            item.setHidden(
                normalized_search_text not in item_text
                and (not canonical_text or normalized_search_text not in canonical_text)
            )

        for item in selected_items:
            item.setSelected(True)

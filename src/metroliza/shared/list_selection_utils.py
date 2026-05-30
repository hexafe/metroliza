"""Shared list-widget selection and filtering helpers for dialogs."""

from collections.abc import Callable

from PyQt6.QtCore import Qt
try:
    from PyQt6.QtCore import QEvent, QObject
except ImportError:  # pragma: no cover - compatibility with narrow Qt test stubs
    QEvent = None

    class QObject:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs):
            pass
import PyQt6.QtWidgets as QtWidgets


class ListSelectionUtils:
    """Provide shared shift-range and search filtering list widget behavior."""

    def __init__(self, keyboard_modifiers: Callable[[], int] | None = None):
        self._last_clicked_row_by_list = {}
        self._keyboard_modifiers = keyboard_modifiers or self._default_keyboard_modifiers
        self._event_filters_by_list = {}

    @staticmethod
    def _default_keyboard_modifiers():
        app_cls = getattr(QtWidgets, "QApplication", None)
        if app_cls is None or not hasattr(app_cls, "keyboardModifiers"):
            return 0
        return app_cls.keyboardModifiers()

    def connect_shift_range_behavior(self, list_widget):
        if list_widget in self._event_filters_by_list:
            return
        if QEvent is not None and hasattr(list_widget, "viewport"):
            viewport = list_widget.viewport()
            if hasattr(viewport, "installEventFilter"):
                event_filter = _ListSelectionEventFilter(self, list_widget)
                viewport.installEventFilter(event_filter)
                self._event_filters_by_list[list_widget] = event_filter
        signal = getattr(list_widget, "itemClicked", None) or getattr(list_widget, "itemPressed", None)
        if signal is not None:
            signal.connect(lambda item, lw=list_widget: self.handle_shift_range_press(lw, item))

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

    def handle_mouse_press(self, list_widget, event) -> bool:
        if event is None or list_widget is None:
            return False
        index = list_widget.indexAt(event.position().toPoint() if hasattr(event, "position") else event.pos())
        if not index.isValid():
            return False

        row = int(index.row())
        modifiers = (
            event.modifiers()
            if hasattr(event, "modifiers")
            else self._keyboard_modifiers()
        )
        is_shift_pressed = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if not is_shift_pressed:
            self._last_clicked_row_by_list[list_widget] = row
            return False

        previous_row = self._last_clicked_row_by_list.get(list_widget)
        if previous_row is None:
            self._last_clicked_row_by_list[list_widget] = row
            return False

        start_row = min(previous_row, row)
        end_row = max(previous_row, row)
        model = list_widget.model()
        if model is None:
            return False

        if not modifiers & Qt.KeyboardModifier.ControlModifier:
            list_widget.clearSelection()
        toggle = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        for item_row in range(start_row, end_row + 1):
            item = list_widget.item(item_row)
            if item is None or item.isHidden():
                continue
            item.setSelected(not item.isSelected() if toggle else True)
        if hasattr(event, "accept"):
            event.accept()
        return True

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


class GroupingShortcutBindings:
    """Centralize keyboard behavior for grouping dialogs backed by list widgets."""

    def __init__(
        self,
        *,
        source_list=None,
        reference_list=None,
        groups_list=None,
        assigned_list=None,
        selected_columns_list=None,
        create_group=None,
        create_group_from_reference=None,
        rename_group=None,
        delete_group=None,
        remove_from_source=None,
        remove_from_assigned=None,
        remove_selected_columns=None,
        focused_line_edits=None,
        error_handler=None,
        qt_namespace=None,
    ):
        self.qt = qt_namespace or Qt
        self.source_list = source_list
        self.reference_list = reference_list
        self.groups_list = groups_list
        self.assigned_list = assigned_list
        self.selected_columns_list = selected_columns_list
        self.create_group = create_group
        self.create_group_from_reference = create_group_from_reference
        self.rename_group = rename_group
        self.delete_group = delete_group
        self.remove_from_source = remove_from_source
        self.remove_from_assigned = remove_from_assigned
        self.remove_selected_columns = remove_selected_columns
        self.focused_line_edits = tuple(focused_line_edits or ())
        self.error_handler = error_handler

    def handle_key_press(self, event) -> bool:
        try:
            pressed_key = event.key() if event is not None and hasattr(event, "key") else None
            if pressed_key in self._enter_keys():
                return self._handle_enter(event)
            if pressed_key in self._delete_keys():
                return self._handle_delete(event)
        except Exception as exc:  # pragma: no cover - defensive UI safety path
            if callable(self.error_handler):
                self.error_handler(exc)
                return True
            raise
        return False

    def _handle_enter(self, event) -> bool:
        line_edit_matched, line_edit_action = self._line_edit_action_for_focus()
        if line_edit_matched:
            self._call(line_edit_action)
            self._accept(event)
            return True
        if self._list_or_viewport_has_focus(self.reference_list):
            self._call(self.create_group_from_reference)
            self._accept(event)
            return True
        if self._list_or_viewport_has_focus(self.source_list):
            self._call(self.create_group)
            self._accept(event)
            return True
        if self._list_or_viewport_has_focus(self.groups_list):
            self._call(self.rename_group)
            self._accept(event)
            return True
        if self._list_or_viewport_has_focus(self.assigned_list):
            self._accept(event)
            return True
        return False

    def _line_edit_action_for_focus(self):
        for entry in self.focused_line_edits:
            if isinstance(entry, (tuple, list)):
                widget = entry[0] if entry else None
                action = entry[1] if len(entry) > 1 else None
            else:
                widget = entry
                action = None
            if self._widget_has_focus(widget):
                return True, action
        return False, None

    def _handle_delete(self, event) -> bool:
        actions = (
            (self.source_list, self.remove_from_source),
            (self.assigned_list, self.remove_from_assigned),
            (self.selected_columns_list, self.remove_selected_columns),
            (self.groups_list, self.delete_group),
        )
        for list_widget, action in actions:
            if self._list_or_viewport_has_focus(list_widget):
                self._call(action)
                self._accept(event)
                return True
        return False

    @staticmethod
    def _call(callback):
        if callable(callback):
            callback()

    @staticmethod
    def _accept(event):
        if event is not None and hasattr(event, "accept"):
            event.accept()

    def _enter_keys(self):
        return self._key_candidates("Key_Return", "Key_Enter")

    def _delete_keys(self):
        return self._key_candidates("Key_Delete", "Key_Backspace")

    def _key_candidates(self, *names):
        key_enum = getattr(self.qt, "Key", None)
        candidates = []
        for name in names:
            key = getattr(key_enum, name, None)
            if key is None:
                continue
            candidates.append(key)
            value = getattr(key, "value", None)
            if value is not None:
                candidates.append(value)
            try:
                candidates.append(int(key))
            except (TypeError, ValueError):
                pass
        return tuple(candidates)

    @staticmethod
    def _list_or_viewport_has_focus(list_widget) -> bool:
        if list_widget is None:
            return False
        if GroupingShortcutBindings._widget_has_focus(list_widget):
            return True
        if hasattr(list_widget, "viewport") and list_widget.viewport() is not None:
            return bool(list_widget.viewport().hasFocus())
        return False

    @staticmethod
    def _widget_has_focus(widget) -> bool:
        return bool(widget is not None and hasattr(widget, "hasFocus") and widget.hasFocus())


class _ListSelectionEventFilter(QObject):
    def __init__(self, helper: ListSelectionUtils, list_widget):
        super().__init__(list_widget)
        self._helper = helper
        self._list_widget = list_widget

    def eventFilter(self, watched, event) -> bool:
        if QEvent is None:
            return False
        try:
            viewport = self._list_widget.viewport()
        except RuntimeError:
            return False
        if watched is viewport and event.type() == QEvent.Type.MouseButtonPress:
            return self._helper.handle_mouse_press(self._list_widget, event)
        return False

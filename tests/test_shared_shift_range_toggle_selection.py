import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class _FakeSignal:
    def connect(self, callback, *_args, **_kwargs):
        self._callback = callback
        return None


class _FakeQDate:
    @staticmethod
    def currentDate():
        return _FakeQDate()


class _FakeQt:
    KeyboardModifier = types.SimpleNamespace(ShiftModifier=1)
    ItemDataRole = types.SimpleNamespace(UserRole=0)


class _FakeDialog:
    def __init__(self, *args, **kwargs):
        del args, kwargs


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        del args, kwargs


class _FakeItem:
    def __init__(self, text, user_role=None):
        self._text = text
        self._selected = False
        self._hidden = False
        self._user_role = user_role

    def text(self):
        return self._text

    def data(self, _role):
        return self._user_role

    def setSelected(self, selected):
        self._selected = bool(selected)

    def isSelected(self):
        return self._selected

    def isHidden(self):
        return self._hidden

    def setHidden(self, hidden):
        self._hidden = bool(hidden)


class _FakeListWidget:
    def __init__(self):
        self._items = []
        self._current_item = None
        self.itemPressed = _FakeSignal()

    def addItem(self, item):
        self._items.append(item)

    def item(self, index):
        return self._items[index]

    def count(self):
        return len(self._items)

    def row(self, item):
        return self._items.index(item)

    def setCurrentItem(self, item):
        self._current_item = item

    def selectedItems(self):
        return [item for item in self._items if item.isSelected()]

    def clearSelection(self):
        for item in self._items:
            item.setSelected(False)


class _FakeColor:
    def __init__(self, *_args, **_kwargs):
        return None

    def isValid(self):
        return True

    def red(self):
        return 255

    def green(self):
        return 255

    def blue(self):
        return 255

    def name(self):
        return "#FFFFFF"

    @staticmethod
    def fromHsl(*_args, **_kwargs):
        return _FakeColor()


class _FakeBrush:
    def __init__(self, *_args, **_kwargs):
        return None


def _install_qt_stubs():
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QDate = _FakeQDate
    qtcore.Qt = _FakeQt

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QDateEdit = _FakeWidget
    qtwidgets.QGridLayout = _FakeWidget
    qtwidgets.QLabel = _FakeWidget
    qtwidgets.QLineEdit = _FakeWidget
    qtwidgets.QListWidget = _FakeListWidget
    qtwidgets.QListWidgetItem = _FakeItem
    qtwidgets.QPushButton = _FakeWidget
    qtwidgets.QInputDialog = _FakeWidget
    qtwidgets.QMessageBox = _FakeWidget
    qtwidgets.QAbstractItemView = types.SimpleNamespace(SelectionMode=types.SimpleNamespace(MultiSelection=2))

    qtgui = types.ModuleType("PyQt6.QtGui")
    qtgui.QColor = _FakeColor
    qtgui.QBrush = _FakeBrush

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtWidgets = qtwidgets

    return pyqt6, qtcore, qtwidgets, qtgui


class TestSharedShiftRangeToggleSelection(unittest.TestCase):
    def _build_list(self):
        list_widget = _FakeListWidget()
        for label in ("A", "B", "C", "D", "E", "F"):
            list_widget.addItem(_FakeItem(label))
        return list_widget

    def _assert_selected_rows(self, list_widget, expected_rows):
        actual = {index for index, item in enumerate(list_widget._items) if item.isSelected()}
        self.assertEqual(actual, set(expected_rows))

    def _run_shared_behavior_test(self, list_selection_utils_cls):
        helper = list_selection_utils_cls(keyboard_modifiers=lambda: 0)
        list_widget = self._build_list()

        helper.handle_shift_range_press(list_widget, list_widget.item(0))
        self.assertEqual(helper._last_clicked_row_by_list[list_widget], 0)

        helper._keyboard_modifiers = lambda: _FakeQt.KeyboardModifier.ShiftModifier
        helper.handle_shift_range_press(list_widget, list_widget.item(3))
        self._assert_selected_rows(list_widget, {0, 1, 2, 3})

        helper.handle_shift_range_press(list_widget, list_widget.item(2))
        self._assert_selected_rows(list_widget, {3})

        helper._keyboard_modifiers = lambda: 0
        helper.handle_shift_range_press(list_widget, list_widget.item(5))
        self.assertEqual(helper._last_clicked_row_by_list[list_widget], 5)

    def _run_filter_preserve_selection_test(self, list_selection_utils_cls, canonical=False):
        helper = list_selection_utils_cls(keyboard_modifiers=lambda: 0)
        list_widget = _FakeListWidget()
        list_widget.addItem(_FakeItem("Fancy Label (n=3)", user_role="CanonicalGroup"))
        list_widget.addItem(_FakeItem("Other Group", user_role="Other"))

        list_widget.item(0).setSelected(True)
        canonical_getter = (lambda item: item.data(_FakeQt.ItemDataRole.UserRole)) if canonical else None

        search_text = "canonical" if canonical else "fancy"
        helper.preserve_selection_during_filter(list_widget, search_text, canonical_getter)

        self.assertFalse(list_widget.item(0).isHidden())
        self.assertTrue(list_widget.item(0).isSelected())
        self.assertTrue(list_widget.item(1).isHidden())

    def test_list_selection_utils_shift_click_selects_then_toggles_selected_range(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
            },
            clear=False,
        ):
            sys.modules.pop("modules.list_selection_utils", None)
            utils_module = importlib.import_module("modules.list_selection_utils")
            self._run_shared_behavior_test(utils_module.ListSelectionUtils)

    def test_list_selection_utils_preserves_selection_while_filtering(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
            },
            clear=False,
        ):
            sys.modules.pop("modules.list_selection_utils", None)
            utils_module = importlib.import_module("modules.list_selection_utils")
            self._run_filter_preserve_selection_test(utils_module.ListSelectionUtils, canonical=False)
            self._run_filter_preserve_selection_test(utils_module.ListSelectionUtils, canonical=True)

    def test_filter_dialog_delegates_shift_and_filter_to_shared_helper(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            sys.modules.pop("modules.filter_dialog", None)
            filter_dialog_module = importlib.import_module("modules.filter_dialog")
            dialog = filter_dialog_module.FilterDialog.__new__(filter_dialog_module.FilterDialog)
            dialog._list_selection_utils = Mock()

            list_widget = _FakeListWidget()
            item = _FakeItem("A")
            dialog._connect_shift_range_for_list(list_widget)
            dialog._handle_list_item_pressed(list_widget, item)
            dialog.search_list_widgets(list_widget, "abc")

            dialog._list_selection_utils.connect_shift_range_behavior.assert_called_once_with(list_widget)
            dialog._list_selection_utils.handle_shift_range_press.assert_called_once_with(list_widget, item)
            dialog._list_selection_utils.preserve_selection_during_filter.assert_called_once_with(list_widget, "abc")

    def test_data_grouping_delegates_shift_and_filter_to_shared_helper(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.read_sql_dataframe = lambda *_args, **_kwargs: None

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            sys.modules.pop("modules.data_grouping", None)
            data_grouping_module = importlib.import_module("modules.data_grouping")
            dialog = data_grouping_module.DataGrouping.__new__(data_grouping_module.DataGrouping)
            dialog._list_selection_utils = Mock()

            list_widget = _FakeListWidget()
            item = _FakeItem("A")
            dialog._connect_shift_range_for_list(list_widget)
            dialog._handle_list_item_pressed(list_widget, item)
            dialog.search_list_widgets(list_widget, "canonical")

            dialog._list_selection_utils.connect_shift_range_behavior.assert_called_once_with(list_widget)
            dialog._list_selection_utils.handle_shift_range_press.assert_called_once_with(list_widget, item)
            kwargs = dialog._list_selection_utils.preserve_selection_during_filter.call_args.kwargs
            self.assertEqual(dialog._list_selection_utils.preserve_selection_during_filter.call_args.args[:2], (list_widget, "canonical"))
            self.assertTrue(callable(kwargs.get("canonical_text_getter")))


if __name__ == "__main__":
    unittest.main()

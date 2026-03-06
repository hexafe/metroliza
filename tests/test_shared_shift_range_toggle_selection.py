import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
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
    def __init__(self, text):
        self._text = text
        self._selected = False
        self._hidden = False

    def text(self):
        return self._text

    def setSelected(self, selected):
        self._selected = bool(selected)

    def isSelected(self):
        return self._selected

    def isHidden(self):
        return self._hidden


class _FakeListWidget:
    def __init__(self):
        self._items = []
        self._current_item = None
        self.itemPressed = _FakeSignal()

    def addItem(self, item):
        self._items.append(item)

    def item(self, index):
        return self._items[index]

    def row(self, item):
        return self._items.index(item)

    def setCurrentItem(self, item):
        self._current_item = item


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

    def _run_shared_behavior_test(self, dialog_cls):
        dialog = dialog_cls.__new__(dialog_cls)
        dialog._last_clicked_row_by_list = {}
        dialog._keyboard_modifiers = lambda: 0

        list_widget = self._build_list()

        dialog_cls._handle_list_item_pressed(dialog, list_widget, list_widget.item(0))
        self.assertEqual(dialog._last_clicked_row_by_list[list_widget], 0)

        dialog._keyboard_modifiers = lambda: _FakeQt.KeyboardModifier.ShiftModifier
        dialog_cls._handle_list_item_pressed(dialog, list_widget, list_widget.item(3))
        self._assert_selected_rows(list_widget, {0, 1, 2, 3})

        dialog_cls._handle_list_item_pressed(dialog, list_widget, list_widget.item(2))
        self._assert_selected_rows(list_widget, {3})

        dialog._keyboard_modifiers = lambda: 0
        dialog_cls._handle_list_item_pressed(dialog, list_widget, list_widget.item(5))
        self.assertEqual(dialog._last_clicked_row_by_list[list_widget], 5)

    def test_filter_dialog_shift_click_selects_then_toggles_selected_range(self):
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
            sys.modules.pop("modules.FilterDialog", None)
            filter_dialog_module = importlib.import_module("modules.FilterDialog")
            self._run_shared_behavior_test(filter_dialog_module.FilterDialog)

    def test_data_grouping_shift_click_selects_then_toggles_selected_range(self):
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
            sys.modules.pop("modules.DataGrouping", None)
            data_grouping_module = importlib.import_module("modules.DataGrouping")
            self._run_shared_behavior_test(data_grouping_module.DataGrouping)


if __name__ == "__main__":
    unittest.main()

import importlib
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeQtKey:
    Key_Delete = 16777223
    Key_Backspace = 16777219
    Key_A = 65


class _FakeQt:
    Key = _FakeQtKey
    KeyboardModifier = types.SimpleNamespace(ShiftModifier=1)
    ItemDataRole = types.SimpleNamespace(UserRole=0)


class _FakeDialog:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def keyPressEvent(self, *_args, **_kwargs):
        return None


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")


class _FakeItem:
    def __init__(self, text, user_data=None):
        self._text = text
        self._selected = False
        self._hidden = False
        self._user_data = user_data

    def text(self):
        return self._text

    def setSelected(self, selected):
        self._selected = bool(selected)

    def isSelected(self):
        return self._selected

    def isHidden(self):
        return self._hidden

    def setHidden(self, hidden):
        self._hidden = bool(hidden)

    def data(self, role):
        if role == _FakeQt.ItemDataRole.UserRole:
            return self._user_data
        return None


class _FakeViewport:
    def __init__(self, owner):
        self._owner = owner

    def hasFocus(self):
        return self._owner._viewport_has_focus


class _FakeListWidget:
    def __init__(self):
        self._items = []
        self._has_focus = False
        self._viewport_has_focus = False
        self._viewport = _FakeViewport(self)
        self.itemPressed = _FakeSignal()
        self.itemSelectionChanged = _FakeSignal()

    def setSelectionMode(self, *_args, **_kwargs):
        return None

    def addItem(self, item):
        if isinstance(item, str):
            item = _FakeItem(item)
        self._items.append(item)

    def selectedItems(self):
        return [item for item in self._items if item.isSelected()]

    def setFocus(self):
        self._has_focus = True
        self._viewport_has_focus = False

    def setViewportFocus(self):
        self._has_focus = False
        self._viewport_has_focus = True

    def clearFocus(self):
        self._has_focus = False
        self._viewport_has_focus = False

    def hasFocus(self):
        return self._has_focus

    def viewport(self):
        return self._viewport


class _FakeButton:
    def __init__(self):
        self.disabled = False

    def setDisabled(self, disabled):
        self.disabled = bool(disabled)


class _FakeKeyEvent:
    def __init__(self, key):
        self._key = key
        self.accepted = False

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True


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
    qtcore.Qt = _FakeQt

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _FakeDialog
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


class TestDataGroupingDeleteKey(unittest.TestCase):
    def _build_dialog(self, data_grouping_module):
        dialog = data_grouping_module.DataGrouping.__new__(data_grouping_module.DataGrouping)
        dialog.default_group = "POPULATION"
        dialog.default_group_color = "#FFFFFF"
        dialog.group_color_column = "GROUP_COLOR"
        dialog.df = pd.DataFrame(
            [
                {"GROUP": "CUSTOM", "GROUP_KEY": "A", "GROUP_COLOR": "#FDE2E4"},
                {"GROUP": "CUSTOM", "GROUP_KEY": "B", "GROUP_COLOR": "#FDE2E4"},
                {"GROUP": "POPULATION", "GROUP_KEY": "C", "GROUP_COLOR": "#FFFFFF"},
            ]
        )
        dialog.part_group_list = _FakeListWidget()
        dialog.part_group_list.addItem(_FakeItem("A", user_data="A"))
        dialog.part_group_list.addItem(_FakeItem("B", user_data="B"))
        dialog.groups_list = types.SimpleNamespace()
        dialog._selected_group_name = lambda: "CUSTOM"
        dialog.remove_from_group_button = _FakeButton()
        dialog.log_and_exit = lambda *_args, **_kwargs: None
        dialog.populate_list_widgets_called = 0
        dialog.populate_list_widgets = lambda *args, **kwargs: setattr(dialog, "populate_list_widgets_called", dialog.populate_list_widgets_called + 1)
        return dialog

    def _load_data_grouping_module(self):
        existing_module = sys.modules.get("modules.DataGrouping")
        if existing_module is not None:
            return existing_module
        return importlib.import_module("modules.DataGrouping")

    def test_delete_key_moves_selected_part_group_items_to_population(self):
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
            data_grouping_module = self._load_data_grouping_module()
            data_grouping_module.Qt = _FakeQt
            setattr(data_grouping_module.DataGrouping.__mro__[1], "keyPressEvent", lambda *_args, **_kwargs: None)
            dialog = self._build_dialog(data_grouping_module)
            dialog.part_group_list._items[1].setSelected(True)
            dialog.part_group_list.setFocus()

            event = _FakeKeyEvent(_FakeQtKey.Key_Delete)
            data_grouping_module.DataGrouping.keyPressEvent(dialog, event)

            self.assertTrue(event.accepted)
            self.assertEqual(dialog.populate_list_widgets_called, 1)
            self.assertTrue(dialog.remove_from_group_button.disabled)
            reassigned = dialog.df.loc[dialog.df["GROUP_KEY"] == "B"].iloc[0]
            untouched = dialog.df.loc[dialog.df["GROUP_KEY"] == "A"].iloc[0]
            self.assertEqual(reassigned["GROUP"], "POPULATION")
            self.assertEqual(reassigned["GROUP_COLOR"], "#FFFFFF")
            self.assertEqual(untouched["GROUP"], "CUSTOM")

    def test_non_delete_key_does_not_reassign_parts(self):
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
            data_grouping_module = self._load_data_grouping_module()
            data_grouping_module.Qt = _FakeQt
            setattr(data_grouping_module.DataGrouping.__mro__[1], "keyPressEvent", lambda *_args, **_kwargs: None)
            dialog = self._build_dialog(data_grouping_module)
            dialog.part_group_list._items[1].setSelected(True)
            dialog.part_group_list.setViewportFocus()

            event = _FakeKeyEvent(_FakeQtKey.Key_A)
            data_grouping_module.DataGrouping.keyPressEvent(dialog, event)

            self.assertFalse(event.accepted)
            self.assertEqual(dialog.populate_list_widgets_called, 0)
            still_custom = dialog.df.loc[dialog.df["GROUP_KEY"] == "B"].iloc[0]
            self.assertEqual(still_custom["GROUP"], "CUSTOM")
            self.assertEqual(still_custom["GROUP_COLOR"], "#FDE2E4")


if __name__ == "__main__":
    unittest.main()

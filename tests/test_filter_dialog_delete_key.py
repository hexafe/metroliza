import importlib
import sys
import types
import unittest
from unittest.mock import patch


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


class _FakeQDate:
    @staticmethod
    def currentDate():
        return _FakeQDate()

    def toString(self, *_args, **_kwargs):
        return "1970-01-01"


class _FakeDialog:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def keyPressEvent(self, *_args, **_kwargs):
        return None


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")


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

    def setHidden(self, hidden):
        self._hidden = bool(hidden)


class _FakeListWidget:
    def __init__(self):
        self._items = []
        self._has_focus = False
        self.itemPressed = _FakeSignal()
        self.itemSelectionChanged = _FakeSignal()

    def setSelectionMode(self, *_args, **_kwargs):
        return None

    def addItem(self, item):
        if isinstance(item, str):
            item = _FakeItem(item)
        self._items.append(item)

    def clear(self):
        self._items = []

    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def row(self, item):
        return self._items.index(item)

    def selectedItems(self):
        return [item for item in self._items if item.isSelected()]

    def clearSelection(self):
        for item in self._items:
            item.setSelected(False)

    def setFocus(self):
        self._has_focus = True

    def clearFocus(self):
        self._has_focus = False

    def hasFocus(self):
        return self._has_focus


class _FakeKeyEvent:
    def __init__(self, key):
        self._key = key
        self.accepted = False

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True


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
    qtwidgets.QMessageBox = _FakeWidget
    qtwidgets.QAbstractItemView = types.SimpleNamespace(SelectionMode=types.SimpleNamespace(MultiSelection=2))

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtWidgets = qtwidgets

    return pyqt6, qtcore, qtwidgets


class TestFilterDialogDeleteKey(unittest.TestCase):
    def test_delete_key_unselects_headers_and_refreshes_selected_headers_list(self):
        pyqt6, qtcore, qtwidgets = _install_qt_stubs()
        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
            },
            clear=False,
        ):
            sys.modules.pop("modules.FilterDialog", None)
            filter_dialog_module = importlib.import_module("modules.FilterDialog")
            dialog = filter_dialog_module.FilterDialog.__new__(filter_dialog_module.FilterDialog)

            dialog.header_list = _FakeListWidget()
            dialog.selected_headers_list = _FakeListWidget()
            dialog.log_and_exit = lambda *_args, **_kwargs: None

            ax = _FakeItem("AX")
            bx = _FakeItem("BX")
            cx = _FakeItem("CX")
            ax.setSelected(True)
            bx.setSelected(True)
            cx.setSelected(True)
            dialog.header_list.addItem(ax)
            dialog.header_list.addItem(bx)
            dialog.header_list.addItem(cx)

            dialog.update_selected_headers = lambda: filter_dialog_module.FilterDialog.update_selected_headers(dialog)
            dialog.update_selected_headers()

            selected_items_before = [item.text() for item in dialog.selected_headers_list.selectedItems()]
            self.assertEqual(selected_items_before, [])
            self.assertEqual([item.text() for item in dialog.selected_headers_list._items], ["AX", "BX", "CX"])

            dialog.selected_headers_list.item(1).setSelected(True)
            dialog.selected_headers_list.setFocus()

            event = _FakeKeyEvent(_FakeQtKey.Key_Delete)
            filter_dialog_module.FilterDialog.keyPressEvent(dialog, event)

            self.assertTrue(event.accepted)
            self.assertTrue(dialog.header_list.item(0).isSelected())
            self.assertFalse(dialog.header_list.item(1).isSelected())
            self.assertTrue(dialog.header_list.item(2).isSelected())
            self.assertEqual([item.text() for item in dialog.selected_headers_list._items], ["AX", "CX"])


if __name__ == "__main__":
    unittest.main()

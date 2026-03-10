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

    def parent(self):
        return self._parent


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def setWordWrap(self, *_args, **_kwargs):
        return None


class _FakeItem:
    def __init__(self, text):
        self._text = text
        self._selected = False

    def text(self):
        return self._text

    def setSelected(self, value):
        self._selected = bool(value)

    def isSelected(self):
        return self._selected

    def isHidden(self):
        return False


class _FakeListWidget:
    def __init__(self):
        self._items = []
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

    def selectedItems(self):
        return [item for item in self._items if item.isSelected()]

    def clearSelection(self):
        for item in self._items:
            item.setSelected(False)


class _FakeCalendarDate:
    def __init__(self, date_str):
        self._date_str = date_str

    def toString(self, *_args, **_kwargs):
        return self._date_str


class _FakeDateEdit:
    def __init__(self, date_str):
        self._date = _FakeCalendarDate(date_str)

    def date(self):
        return self._date


class _FakeParent:
    def __init__(self):
        self.filter_query = None
        self.applied = False

    def set_filter_query(self, query):
        self.filter_query = query

    def set_filter_applied(self):
        self.applied = True


def _install_qt_stubs():
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QDate = _FakeQDate
    qtcore.Qt = _FakeQt

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QDateEdit = _FakeWidget
    qtwidgets.QGridLayout = _FakeWidget
    qtwidgets.QHBoxLayout = _FakeWidget
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


class TestFilterDialogSelectionState(unittest.TestCase):
    def test_apply_filters_treats_empty_and_complete_selection_as_all(self):
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
            module = importlib.import_module("modules.FilterDialog")
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            dialog.log_and_exit = lambda *_args, **_kwargs: None

            parent = _FakeParent()
            dialog.parent = lambda: parent
            dialog.hide = lambda: None

            dialog.ax_list = _FakeListWidget()
            dialog.reference_list = _FakeListWidget()
            dialog.header_list = _FakeListWidget()

            for value in ("A", "B"):
                dialog.ax_list.addItem(_FakeItem(value))
                dialog.reference_list.addItem(_FakeItem(value))
                dialog.header_list.addItem(_FakeItem(value))

            # Complete selection still means "all"
            for list_widget in (dialog.ax_list, dialog.reference_list, dialog.header_list):
                for i in range(list_widget.count()):
                    list_widget.item(i).setSelected(True)

            dialog.date_from_calendar = _FakeDateEdit("2024-01-01")
            dialog.date_to_calendar = _FakeDateEdit("2024-12-31")

            module.FilterDialog.apply_filters(dialog)

            self.assertIsNotNone(parent.filter_query)
            self.assertNotIn("MEASUREMENTS.AX IN", parent.filter_query)
            self.assertNotIn("MEASUREMENTS.HEADER IN", parent.filter_query)
            self.assertNotIn("REPORTS.REFERENCE IN", parent.filter_query)
            self.assertIn("REPORTS.DATE >= '2024-01-01'", parent.filter_query)
            self.assertIn("REPORTS.DATE <= '2024-12-31'", parent.filter_query)

    def test_reference_change_uses_all_headers_when_no_reference_is_selected(self):
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
            module = importlib.import_module("modules.FilterDialog")
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            dialog.log_and_exit = lambda *_args, **_kwargs: None
            dialog.update_selected_headers = lambda: None

            dialog.reference_list = _FakeListWidget()
            dialog.header_list = _FakeListWidget()
            dialog._all_headers = ["H1", "H2"]
            dialog.db_file = "dummy.db"

            module.FilterDialog.on_reference_selection_changed(dialog)

            self.assertEqual([dialog.header_list.item(i).text() for i in range(dialog.header_list.count())], ["H1", "H2"])


if __name__ == "__main__":
    unittest.main()
